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


def _office_to_pdf(source: Path, target: Path) -> Path:
    soffice = shutil.which(settings.soffice_bin)
    if not soffice:
        raise ConversionError("LibreOffice не установлен — конвертация в PDF недоступна")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Отдельный профиль на каждый вызов: иначе параллельные конвертации блокируют друг друга
        profile = (tmp_path / "profile").as_uri()
        cmd = [
            soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
            "--convert-to", "pdf", "--outdir", str(tmp_path), str(source),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=settings.convert_timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Превышено время конвертации документа") from exc

        produced = tmp_path / f"{source.stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            log.error("soffice failed: %s %s", proc.stdout[-500:], proc.stderr[-500:])
            raise ConversionError("Не удалось сконвертировать документ в PDF")
        shutil.move(str(produced), target)
    return target
