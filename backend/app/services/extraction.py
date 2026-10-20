"""Извлечение текста и координат слов из PDF постранично, с OCR для сканов.

Для каждой страницы получаем:
  * text  — текст страницы (строки через \\n) для чанкинга и поиска;
  * words — [[x0, y0, x1, y1, "слово", line_no], ...] в PDF-пунктах для подсветки цитат.

Текстовые страницы читаются из текстового слоя PDF. Страницы без текстового слоя
(сканы) рендерятся и распознаются Tesseract (rus+eng) в нескольких потоках:
pytesseract запускает отдельный процесс, поэтому потоки дают реальный параллелизм.

Два решения, которые сильно влияют на скорость и точность (замеры на 20-страничном скане):
  * скан рендерится в своём родном разрешении, а не растягивается до 300 DPI —
    интерполяция размывает буквы: точность 90,5% -> 99,4%;
  * OMP_THREAD_LIMIT=1 — иначе каждый процесс Tesseract запускает свои потоки OpenMP
    и они дерутся за ядра: 78 с -> 22 с на 2 ядрах.
"""
import logging
import os
import re
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from app.config import settings

# Должно быть выставлено до запуска процессов tesseract (они наследуют окружение)
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

log = logging.getLogger(__name__)


@dataclass
class PageContent:
    page_number: int  # с 1
    width: float
    height: float
    text: str = ""
    words: list[list] = field(default_factory=list)
    is_ocr: bool = False
    ocr_confidence: float | None = None


_CLEAN = str.maketrans({
    "\u00ad": "-",  # мягкий перенос: MuPDF часто отдаёт так и обычный дефис («44-ФЗ»)
    "\u00a0": " ", "\u202f": " ", "\ufb01": "fi", "\ufb02": "fl", "\t": " ",
})


def clean_text(text: str) -> str:
    return text.translate(_CLEAN)


def _words_to_text(words: list[list]) -> str:
    lines: list[str] = []
    current_line = None
    for w in words:
        if w[5] != current_line:
            lines.append(w[4])
            current_line = w[5]
        else:
            lines[-1] += " " + w[4]
    return "\n".join(lines)


def _native_page(page: fitz.Page, page_number: int) -> PageContent:
    raw = page.get_text("words", sort=True)  # (x0, y0, x1, y1, word, block, line, word_no)
    words: list[list] = []
    line_ids: dict[tuple[int, int], int] = {}
    for x0, y0, x1, y1, word, block, line, _ in raw:
        word = clean_text(word).strip()
        if not word:
            continue
        line_no = line_ids.setdefault((block, line), len(line_ids))
        words.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), word, line_no])
    return PageContent(
        page_number=page_number,
        width=round(page.rect.width, 1),
        height=round(page.rect.height, 1),
        text=_words_to_text(words),
        words=words,
    )


def _image_coverage(page: fitz.Page) -> float:
    """Доля площади страницы, занятая картинками."""
    area = abs(page.rect) or 1
    covered = sum(abs(fitz.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return min(covered / area, 1.0)


_GOOD_CHARS = set(".,;:!?()[]«»\"'-–—№%/\\+=*<>§$€₽")


def _is_junk_text(text: str) -> bool:
    """Текстовый слой есть, но это не буквы и цифры (битая кодировка шрифта, мусор сканера)."""
    chars = "".join(text.split())
    if not chars:
        return False
    good = sum(ch.isalnum() or ch in _GOOD_CHARS for ch in chars)
    junk = sum(ch == "\ufffd" or "\ue000" <= ch <= "\uf8ff" or ch < " " for ch in chars)
    return good / len(chars) < 0.6 or junk / len(chars) > 0.1


def _needs_ocr(page: fitz.Page, native: PageContent) -> bool:
    if not settings.ocr_enabled:
        return False
    chars = len("".join(native.text.split()))
    if chars < settings.ocr_min_text_chars:
        # Пустая страница без картинок — просто пустая страница
        return bool(page.get_images(full=False)) or bool(page.get_drawings())
    if _is_junk_text(native.text):
        return True
    # Скан со штампом «Документ подписан ЭП…» или колонтитулом в текстовом слое: так приходят
    # документы из ЕИС и с площадок. Текста немного, а вся страница — картинка.
    if chars < settings.ocr_scan_max_text_chars and _image_coverage(page) > 0.8:
        return True
    return False


def _scan_dpi(page: fitz.Page) -> int | None:
    """Разрешение картинки, занимающей большую часть страницы (самого скана), или None."""
    page_area = abs(page.rect) or 1
    best = None
    for info in page.get_image_info():
        bbox = fitz.Rect(info["bbox"]) & page.rect
        if abs(bbox) < 0.5 * page_area or bbox.width <= 0 or bbox.height <= 0:
            continue
        # картинка может быть повёрнута на 90° (альбомный скан на книжной странице)
        same_orientation = (info["width"] >= info["height"]) == (bbox.width >= bbox.height)
        span_inch = (bbox.width if same_orientation else bbox.height) / 72
        best = max(best or 0, round(info["width"] / span_inch))
    return best


def _render(page: fitz.Page) -> Image.Image:
    longest_inch = max(page.rect.width, page.rect.height) / 72
    native = _scan_dpi(page)
    if native:
        # Скан рендерим ровно в его пикселях: растягивание 200 DPI до 300 размывает буквы
        # и снижает точность Tesseract. Увеличиваем только совсем мелкие картинки (фото,
        # сканы 100 DPI), чтобы длинная сторона была около 2000 px.
        dpi = native
        if native * longest_inch < 1700:
            dpi = native * 2000 / (native * longest_inch)
    else:
        dpi = settings.ocr_dpi  # векторная страница без текста (кривые вместо шрифта)
    # огромные страницы (чертежи A0) ограничиваем по пикселям, чтобы не съесть память
    dpi = min(dpi, 600, 9000 / max(longest_inch, 1))
    pix = page.get_pixmap(dpi=max(int(dpi), 72), colorspace=fitz.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def ocr_image(image: Image.Image, page_number: int, width: float, height: float) -> PageContent:
    import pytesseract

    config = "--oem 1 --psm 3"
    if settings.tessdata_prefix:
        config += f' --tessdata-dir "{settings.tessdata_prefix}"'
    data = pytesseract.image_to_data(
        image, lang=settings.ocr_languages, config=config, output_type=pytesseract.Output.DICT
    )
    scale_x = width / image.width
    scale_y = height / image.height

    words: list[list] = []
    confidences: list[float] = []
    line_ids: dict[tuple[int, int, int], int] = {}
    for i, raw_word in enumerate(data["text"]):
        word = clean_text(raw_word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line_no = line_ids.setdefault(key, len(line_ids))
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append([
            round(x * scale_x, 1), round(y * scale_y, 1),
            round((x + w) * scale_x, 1), round((y + h) * scale_y, 1),
            word, line_no,
        ])
        confidences.append(conf)

    return PageContent(
        page_number=page_number,
        width=round(width, 1),
        height=round(height, 1),
        text=_words_to_text(words),
        words=words,
        is_ocr=True,
        ocr_confidence=round(sum(confidences) / len(confidences), 1) if confidences else None,
    )


def extract_pages(pdf_path: Path, on_page: Callable[[int, int], None] | None = None) -> list[PageContent]:
    """Возвращает содержимое всех страниц по порядку. on_page(done, total) — для прогресса."""
    with fitz.open(pdf_path) as doc:
        total = doc.page_count
        results: list[PageContent | None] = [None] * total
        pending: dict[int, Future] = {}
        done = 0

        def report() -> None:
            if on_page:
                on_page(done, total)

        with ThreadPoolExecutor(max_workers=max(1, settings.ocr_threads)) as pool:
            for index in range(total):
                page = doc[index]
                native = _native_page(page, index + 1)
                if _needs_ocr(page, native):
                    # Ограничиваем число отрендеренных страниц в памяти (~9 МБ на страницу A4)
                    while len(pending) >= settings.ocr_threads * 2:
                        done += _collect_one(pending, results)
                        report()
                    image = _render(page)
                    pending[index] = pool.submit(ocr_image, image, index + 1, native.width, native.height)
                    results[index] = native  # запасной вариант, если OCR упадёт
                else:
                    results[index] = native
                    done += 1
                    report()
            while pending:
                done += _collect_one(pending, results)
                report()

    return [r for r in results if r is not None]


def _collect_one(pending: dict[int, Future], results: list) -> int:
    index = next(iter(pending))
    future = pending.pop(index)
    try:
        results[index] = future.result()
    except Exception:  # noqa: BLE001 — страница остаётся с текстовым слоем
        log.exception("OCR failed on page %s", index + 1)
    return 1


def iter_lines(pages: list[PageContent]) -> Iterator[tuple[int, str]]:
    for page in pages:
        for line in page.text.splitlines():
            if line.strip():
                yield page.page_number, line


_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def dehyphenate(text: str) -> str:
    return _HYPHEN_BREAK.sub(r"\1\2", text)
