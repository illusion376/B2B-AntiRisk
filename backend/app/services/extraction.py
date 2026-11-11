"""Извлечение текста и координат слов из PDF постранично, с OCR для сканов.

Для каждой страницы получаем:
  * text  — текст страницы (строки через \\n) для чанкинга и поиска;
  * words — [[x0, y0, x1, y1, "слово", line_no], ...] в PDF-пунктах для подсветки цитат.

Текстовые страницы читаются из текстового слоя PDF. Страницы без текстового слоя
(сканы) рендерятся в 300 DPI и распознаются Tesseract (rus+eng) в нескольких потоках:
pytesseract запускает отдельный процесс, поэтому потоки дают реальный параллелизм.
"""
import logging
import math
import re
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from app.config import settings

log = logging.getLogger(__name__)

@dataclass
class PageContent:
    page_number: int
    width: float
    height: float
    text: str = ""
    words: list[list] = field(default_factory=list)
    is_ocr: bool = False
    ocr_confidence: float | None = None
    # A failed/disabled OCR page is still an image page, never a native success.
    ocr_error: str | None = None

_CLEAN = str.maketrans({
    "\u00ad": "-",
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
    raw = page.get_text("words", sort=True)
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

# Detect a scanned sheet with a short, selectable header/footer. A small logo
# must not cause an otherwise readable text page to be rasterized again.
_DOMINANT_IMAGE_PAGE_SHARE = 0.65
_HYBRID_NATIVE_TEXT_LIMIT = 200

def _needs_ocr(page: fitz.Page, native: PageContent) -> bool:
    """Use OCR for sparse text over a dominant raster, as well as plain scans.

    200 characters permits typical headers/footers; one visible image must cover
    at least 65% of the page. This deliberately conservative heuristic avoids
    OCR for small stamps/logos and preserves substantial existing text layers,
    including external OCR layers whose original confidence is unavailable.
    It does not infer image content or prove that every raster contains text.
    """
    text_chars = len(native.text.strip())
    if text_chars < settings.ocr_min_text_chars:
        return bool(page.get_images(full=False)) or bool(page.get_drawings())
    if text_chars >= _HYBRID_NATIVE_TEXT_LIMIT:
        return False

    page_area = page.rect.get_area()
    if page_area <= 0:
        return False
    return any(
        (fitz.Rect(image["bbox"]) & page.rect).get_area() / page_area >= _DOMINANT_IMAGE_PAGE_SHARE
        for image in page.get_image_info()
    )

def _render(page: fitz.Page) -> Image.Image:
    pix = page.get_pixmap(dpi=settings.ocr_dpi, colorspace=fitz.csGRAY, alpha=False)
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
        if not word or not math.isfinite(conf) or not 0 <= conf <= 100:
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
        # Compare the measured value with quality thresholds before rounding for display.
        ocr_confidence=sum(confidences) / len(confidences) if confidences else None,
        ocr_error=None if words else "ocr_empty",
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
                    native.is_ocr = True
                    results[index] = native
                    if not settings.ocr_enabled:
                        native.ocr_error = "ocr_disabled"
                        done += 1
                        report()
                        continue
                    while len(pending) >= settings.ocr_threads * 2:
                        done += _collect_one(pending, results)
                        report()
                    try:
                        image = _render(page)
                    except Exception:  # noqa: BLE001 — retain diagnostics for this page
                        log.exception("Could not render OCR page %s", index + 1)
                        native.ocr_error = "ocr_failed"
                        done += 1
                        report()
                        continue
                    pending[index] = pool.submit(ocr_image, image, index + 1, native.width, native.height)
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
        results[index].is_ocr = True
        results[index].ocr_confidence = None
        results[index].ocr_error = "ocr_failed"
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
