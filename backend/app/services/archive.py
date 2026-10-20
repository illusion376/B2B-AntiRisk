"""Безопасная распаковка архивов с документацией закупки: ZIP, RAR, 7Z (и вложенные друг в друга).

Защита: лимит на число файлов и распакованный объём (zip-бомбы), отбрасывание абсолютных
путей и «..» (zip slip), пропуск symlink-ов и служебного мусора (__MACOSX, Thumbs.db, ~$…).
Зашифрованный файл внутри архива не отклоняет всю загрузку: он попадает в список
со словом «не проверялся», остальные документы обрабатываются.
"""
import io
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.storage import ARCHIVES, SUPPORTED_DOCUMENTS, extension, safe_filename

_COPY_CHUNK = 1024 * 1024
ENCRYPTED_MESSAGE = "Файл в архиве защищён паролем — не проверялся"


class ArchiveError(ValueError):
    pass


class ArchiveLimitError(ArchiveError):
    """Превышены лимиты (zip-бомба): отклоняем всю загрузку, даже если это вложенный архив."""


@dataclass
class ExtractedFile:
    relative_path: str  # путь внутри архива, как его увидит пользователь
    stored_path: Path
    size: int
    ext: str
    supported: bool
    error: str | None = None  # почему файл не будет проверен (пароль и т. п.)


def archive_kind(path: Path) -> str | None:
    """Тип архива по сигнатуре: расширению из архива верить нельзя."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    return None


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
            raise ArchiveLimitError("В архиве слишком много файлов")
        if self.bytes_left < 0:
            raise ArchiveLimitError("Распакованный размер архива превышает допустимый")

    def check_total(self, files: int, size: int) -> None:
        """Быстрая проверка по заголовкам до распаковки (zip-бомба отсекается сразу)."""
        if files > self.files_left:
            raise ArchiveLimitError("В архиве слишком много файлов")
        if size > self.bytes_left:
            raise ArchiveLimitError("Распакованный размер архива превышает допустимый")


class _Extractor:
    def __init__(self, target_dir: Path, budget: _Budget):
        self.target_dir = target_dir
        self.budget = budget
        self.result: list[ExtractedFile] = []

    # --- общая часть для всех форматов ---

    def add(self, rel: PurePosixPath, src, size: int, depth: int) -> None:
        """Сохраняет файл из потока src; вложенный архив распаковывает «в папку» с его именем."""
        ext = extension(rel.name)
        stored = self.target_dir / f"{uuid.uuid4().hex}{ext}"
        written = 0
        with open(stored, "wb") as dst:
            while chunk := src.read(_COPY_CHUNK):
                written += len(chunk)
                if written > size + _COPY_CHUNK:  # заголовку архива нельзя доверять слепо
                    raise ArchiveLimitError(f"Размер файла {rel.name} не совпадает с заявленным в архиве")
                dst.write(chunk)

        error = None
        if ext in ARCHIVES:
            if not archive_kind(stored):
                error = "Вложенный архив повреждён — не проверялся"
            elif depth <= 0:
                error = "Слишком глубокая вложенность архивов — не проверялся"
            else:
                try:
                    self.extract(stored, rel, depth - 1)
                except ArchiveLimitError:
                    raise
                except ArchiveError as exc:  # битый или запароленный вложенный архив
                    error = f"Вложенный архив не распакован: {exc}"
                else:
                    stored.unlink(missing_ok=True)
                    return
        self.result.append(ExtractedFile(
            relative_path=str(rel), stored_path=stored, size=written, ext=ext,
            supported=error is None and ext in SUPPORTED_DOCUMENTS, error=error,
        ))

    def add_encrypted(self, rel: PurePosixPath) -> None:
        stored = self.target_dir / f"{uuid.uuid4().hex}{extension(rel.name)}"
        stored.touch()  # у документа должен быть путь; содержимое без пароля не получить
        self.result.append(ExtractedFile(
            relative_path=str(rel), stored_path=stored, size=0, ext=extension(rel.name),
            supported=False, error=ENCRYPTED_MESSAGE,
        ))

    def extract(self, source, prefix: PurePosixPath, depth: int) -> None:
        kind = archive_kind(source) if isinstance(source, Path) else "zip"
        if kind == "zip":
            self._zip(source, prefix, depth)
        elif kind == "rar":
            self._rar(source, prefix, depth)
        elif kind == "7z":
            self._7z(source, prefix, depth)
        else:
            raise ArchiveError("Файл повреждён или не является архивом (поддерживаются ZIP, RAR, 7Z)")

    # --- форматы ---

    def _zip(self, source, prefix: PurePosixPath, depth: int) -> None:
        try:
            zf = zipfile.ZipFile(source)
        except zipfile.BadZipFile as exc:
            raise ArchiveError("Файл повреждён или не является ZIP-архивом") from exc
        with zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            self.budget.check_total(len(infos), sum(i.file_size for i in infos))
            for info in infos:
                member = _normalize_member_path(decode_zip_name(info))
                if member is None or _is_junk(member):
                    continue
                self.budget.take(info.file_size)
                rel = prefix / member
                if info.flag_bits & 0x1:
                    self.add_encrypted(rel)
                    continue
                with zf.open(info) as src:
                    self.add(rel, src, info.file_size, depth)

    def _rar(self, source: Path, prefix: PurePosixPath, depth: int) -> None:
        import rarfile

        try:
            rf = rarfile.RarFile(source)
        except rarfile.NeedFirstVolume as exc:
            raise ArchiveError("Это не первый том многотомного RAR-архива") from exc
        except rarfile.PasswordRequired as exc:
            raise ArchiveError("Архив защищён паролем") from exc
        except rarfile.Error as exc:
            raise ArchiveError("Файл повреждён или не является RAR-архивом") from exc
        with rf:
            infos = [i for i in rf.infolist() if i.is_file()]  # каталоги и symlink-и пропускаем
            self.budget.check_total(len(infos), sum(i.file_size for i in infos))
            for info in infos:
                member = _normalize_member_path(info.filename)
                if member is None or _is_junk(member):
                    continue
                self.budget.take(info.file_size)
                rel = prefix / member
                if info.needs_password():
                    self.add_encrypted(rel)
                    continue
                try:
                    with rf.open(info) as src:
                        self.add(rel, src, info.file_size, depth)
                except rarfile.RarCannotExec as exc:
                    raise ArchiveError("Для RAR-архивов на сервере нужен unar или unrar") from exc

    def _7z(self, source: Path, prefix: PurePosixPath, depth: int) -> None:
        import py7zr

        staging = self.target_dir / f".7z_{uuid.uuid4().hex}"
        try:
            with py7zr.SevenZipFile(source, "r") as z:
                if z.needs_password():
                    raise ArchiveError("Архив защищён паролем")
                infos = [f for f in z.list() if not f.is_directory]
                self.budget.check_total(len(infos), sum(f.uncompressed or 0 for f in infos))
                # py7zr не умеет отдавать файлы потоком по одному — распаковываем во временную
                # папку и затем проверяем каждый путь сами
                z.extractall(path=staging)
        except ArchiveError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except (py7zr.exceptions.PasswordRequired, py7zr.exceptions.UnsupportedCompressionMethodError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise ArchiveError("Архив защищён паролем или сжат неподдерживаемым методом") from exc
        except Exception as exc:  # noqa: BLE001 — любая ошибка py7zr = битый архив
            shutil.rmtree(staging, ignore_errors=True)
            raise ArchiveError("Файл повреждён или не является 7Z-архивом") from exc

        try:
            root = staging.resolve()
            for dirpath, _dirs, files in os.walk(staging, followlinks=False):
                for name in sorted(files):
                    path = Path(dirpath) / name
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        continue
                    member = _normalize_member_path(str(path.relative_to(staging)))
                    if member is None or _is_junk(member):
                        continue
                    size = path.stat().st_size
                    self.budget.take(size)
                    with open(path, "rb") as src:
                        self.add(prefix / member, src, size, depth)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def extract_archive(
    source: Path | io.BytesIO,
    target_dir: Path,
    *,
    max_files: int,
    max_unpacked_bytes: int,
    max_depth: int = 2,
) -> list[ExtractedFile]:
    target_dir.mkdir(parents=True, exist_ok=True)
    extractor = _Extractor(target_dir, _Budget(max_files, max_unpacked_bytes))
    extractor.extract(source, PurePosixPath(), max_depth)
    extractor.result.sort(key=lambda f: f.relative_path.lower())
    return extractor.result


# Прежнее имя: ZIP-only API остаётся рабочим
extract_zip = extract_archive
