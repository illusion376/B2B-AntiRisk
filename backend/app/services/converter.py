"""Приведение любого поддерживаемого документа к PDF.

PDF — единый формат для просмотрщика на фронтенде, номеров страниц в цитатах и подсветки.
docx/doc/rtf/odt/txt конвертируются LibreOffice, изображения — PyMuPDF.
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf as fitz

from app.config import settings
from app.services.storage import IMAGES, NEEDS_CONVERSION

log = logging.getLogger(__name__)


class ConversionError(RuntimeError):
    pass


def to_pdf(source: Path, target: Path) -> Path:
    ext = source.suffix.lower()
    if ext == ".pdf":
        _check_pdf(source)
        return source
    if ext in IMAGES:
        return _image_to_pdf(source, target)
    if ext == ".txt":
        return _text_to_pdf(source, target)
    if ext in NEEDS_CONVERSION:
        return _office_to_pdf(source, target)
    raise ConversionError(f"Формат {ext} не поддерживается")


def _check_pdf(path: Path) -> None:
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ConversionError("PDF защищён паролем")
            if doc.page_count == 0:
                raise ConversionError("PDF не содержит страниц")
    except fitz.FileDataError as exc:
        raise ConversionError("PDF повреждён") from exc


def _image_to_pdf(source: Path, target: Path) -> Path:
    # Многостраничный TIFF тоже поддерживается: каждый кадр -> страница
    with fitz.open(source) as img, fitz.open() as out:
        for page_index in range(img.page_count):
            pdf_bytes = img.convert_to_pdf(page_index, page_index)
            with fitz.open("pdf", pdf_bytes) as page_pdf:
                out.insert_pdf(page_pdf)
        out.save(target, garbage=3, deflate=True)
    return target


def _soffice_convert(source: Path, out_dir: Path, target_format: str) -> Path:
    soffice = shutil.which(settings.soffice_bin)
    if not soffice:
        raise ConversionError("LibreOffice не установлен — конвертация документа недоступна")
    # Отдельный профиль на каждый вызов: иначе параллельные конвертации блокируют друг друга
    profile = (out_dir / "profile").as_uri()
    cmd = [
        soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
        "--convert-to", target_format, "--outdir", str(out_dir), str(source),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=settings.convert_timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("Превышено время конвертации документа") from exc

    produced = out_dir / f"{source.stem}.{target_format}"
    if proc.returncode != 0 or not produced.exists():
        log.error("soffice failed: %s %s", proc.stdout[-500:], proc.stderr[-500:])
        raise ConversionError("Не удалось сконвертировать документ (файл повреждён или защищён паролем)")
    return produced


def _office_to_pdf(source: Path, target: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        produced = _soffice_convert(source, Path(tmp), "pdf")
        shutil.move(str(produced), target)
    return target


# ---------- TXT ----------

def decode_text(raw: bytes) -> str:
    """Текст в UTF-8/UTF-16 или в одной из русских однобайтовых кодировок."""
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes

    best = from_bytes(raw, cp_isolation=["cp1251", "koi8_r", "cp866"]).best()
    return str(best) if best else raw.decode("cp1251", errors="replace")


def _text_to_pdf(source: Path, target: Path) -> Path:
    # LibreOffice читает .txt в системной кодировке и превращает cp1251 в мусор —
    # перекодируем в UTF-8 с BOM, который он распознаёт однозначно
    with tempfile.TemporaryDirectory() as tmp:
        utf8 = Path(tmp) / f"{source.stem}.txt"
        utf8.write_text(decode_text(source.read_bytes()), encoding="utf-8-sig")
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        produced = _soffice_convert(utf8, out_dir, "pdf")
        shutil.move(str(produced), target)
    return target
