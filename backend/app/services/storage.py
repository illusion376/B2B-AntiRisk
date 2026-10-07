"""Раскладка файлов на диске: storage/<analysis_id>/{upload,files,preview,reports}."""
import re
import uuid
from pathlib import Path

from app.config import settings

SUPPORTED_DOCUMENTS = {
    ".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
}
ARCHIVES = {".zip", ".rar", ".7z"}
NEEDS_CONVERSION = {".docx", ".doc", ".rtf", ".odt", ".txt"}
IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def analysis_dir(analysis_id: uuid.UUID) -> Path:
    path = settings.storage_dir / str(analysis_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def subdir(analysis_id: uuid.UUID, name: str) -> Path:
    path = analysis_dir(analysis_id) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, default: str = "file") -> str:
    """Имя файла без путей и запрещённых символов (кириллицу сохраняем)."""
    name = Path(name.replace("\\", "/")).name
    name = _UNSAFE.sub("_", name).strip(" .")
    return name[:200] or default


def extension(name: str) -> str:
    return Path(name).suffix.lower()
