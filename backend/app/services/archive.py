"""Безопасная распаковка ZIP-архивов с документацией закупки."""
import io
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.storage import ARCHIVES, SUPPORTED_DOCUMENTS, extension, safe_filename


class ArchiveError(ValueError):
    pass


@dataclass
class ExtractedFile:
    relative_path: str  # путь внутри архива, как его увидит пользователь
    stored_path: Path
    size: int
    ext: str
    supported: bool


def decode_zip_name(info: zipfile.ZipInfo) -> str:
    """Имена в архивах, созданных в Windows, часто в CP866 без UTF-8 флага.

    Python в этом случае декодирует их как CP437 — получаем «кракозябры». Перекодируем обратно.
    """
    name = info.filename
    if info.flag_bits & 0x800:  # имя уже в UTF-8
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


def _normalize_member_path(name: str) -> PurePosixPath | None:
    """Отбрасывает абсолютные пути и «..» (zip slip)."""
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("", ".", "/")]
    if not parts or any(p == ".." for p in parts) or ":" in parts[0]:
        return None
    return PurePosixPath(*[safe_filename(p) for p in parts])


def _is_junk(path: PurePosixPath) -> bool:
    return (
        any(part == "__MACOSX" for part in path.parts)
        or path.name.startswith(("~$", "._"))
        or path.name in {".DS_Store", "Thumbs.db", "desktop.ini"}
    )


class _Budget:
    def __init__(self, max_files: int, max_bytes: int):
        self.files_left = max_files
        self.bytes_left = max_bytes

    def take(self, size: int) -> None:
        self.files_left -= 1
        self.bytes_left -= size
        if self.files_left < 0:
            raise ArchiveError("В архиве слишком много файлов")
        if self.bytes_left < 0:
            raise ArchiveError("Распакованный размер архива превышает допустимый")


def extract_zip(
    source: Path | io.BytesIO,
    target_dir: Path,
    *,
    max_files: int,
    max_unpacked_bytes: int,
    max_depth: int = 2,
) -> list[ExtractedFile]:
    target_dir.mkdir(parents=True, exist_ok=True)
    budget = _Budget(max_files, max_unpacked_bytes)
    result: list[ExtractedFile] = []
    _extract(source, target_dir, PurePosixPath(), budget, max_depth, result)
    result.sort(key=lambda f: f.relative_path.lower())
    return result


def _extract(source, target_dir: Path, prefix: PurePosixPath, budget: _Budget, depth: int,
             result: list[ExtractedFile]) -> None:
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Файл повреждён или не является ZIP-архивом") from exc

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            member = _normalize_member_path(decode_zip_name(info))
            if member is None or _is_junk(member):
                continue
            if info.flag_bits & 0x1:
                raise ArchiveError(f"Архив защищён паролем: {member}")
            budget.take(info.file_size)

            rel = prefix / member
            ext = extension(member.name)

            if ext in ARCHIVES:
                if depth <= 0:
                    continue
                # Вложенный архив распаковываем «в папку» с его именем
                with zf.open(info) as src:
                    nested = io.BytesIO(src.read())
                _extract(nested, target_dir, rel, budget, depth - 1, result)
                continue

            stored = target_dir / f"{uuid.uuid4().hex}{ext}"
            with zf.open(info) as src, open(stored, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            # zipfile не отдаёт больше file_size из заголовка и сверяет CRC,
            # поэтому бюджет, учтённый выше, честный
            result.append(ExtractedFile(
                relative_path=str(rel),
                stored_path=stored,
                size=stored.stat().st_size,
                ext=ext,
                supported=ext in SUPPORTED_DOCUMENTS,
            ))

