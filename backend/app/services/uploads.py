"""Приём загруженного файла: сохранение, проверка, распаковка ZIP, создание анализа и документов."""
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Analysis, Document, Project, User
from app.services import storage
from app.services.analysis_modes import resolve_analysis_mode
from app.services.archive import ArchiveError, extract_zip
from app.services.audit import log_action

log = logging.getLogger(__name__)

_MAGIC = {".pdf": b"%PDF", ".zip": b"PK", ".docx": b"PK", ".odt": b"PK", ".doc": b"\xd0\xcf\x11\xe0", ".rtf": b"{\\rtf"}


class UploadRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _save(upload: UploadFile, target: Path) -> int:
    size = 0
    with open(target, "wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise UploadRejected(413, f"Размер файла превышает {settings.max_upload_mb} МБ")
            out.write(chunk)
    if size == 0:
        raise UploadRejected(400, "Файл пустой. Выберите файл с содержимым")
    return size


def _check_magic(path: Path, ext: str) -> None:
    magic = _MAGIC.get(ext)
    if magic is None:
        return
    with open(path, "rb") as f:
        head = f.read(1024)
    window = head if ext == ".pdf" else head[: len(magic)]
    if magic not in window:
        raise UploadRejected(400, f"Содержимое файла не соответствует расширению {ext}")


def create_analysis(db: Session, user: User, upload: UploadFile, law_type: str = "AUTO",
                    project: Project | None = None, title: str | None = None,
                    *, defer_processing: bool = False, analysis_mode: str | None = None) -> tuple[Analysis, list[uuid.UUID]]:
    """Сохраняет файл и создаёт анализ с документами (без коммита).

    Возвращает анализ и id поддерживаемых документов. При defer_processing они
    остаются UPLOADED до явного запуска пользователем, иначе готовы к постановке в очередь.
    """
    # Отложенная загрузка не требует настройки движка: пользователь выберет его при запуске.
    mode = resolve_analysis_mode(analysis_mode) if not defer_processing or analysis_mode is not None else None
    original_name = storage.safe_filename(upload.filename or "document")
    ext = storage.extension(original_name)
    if ext not in storage.SUPPORTED_DOCUMENTS | storage.ARCHIVES:
        raise UploadRejected(415, f"Формат {ext or 'без расширения'} не поддерживается. "
                                  "Загрузите PDF, TXT, ZIP, DOCX, DOC, RTF, ODT или изображение")

    initial_status = "UPLOADED" if defer_processing else "QUEUED"
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id if project else None,
        title=(title or Path(original_name).stem)[:255],
        original_filename=original_name,
        file_type=ext.lstrip("."),
        law_type=law_type,
        analysis_status=initial_status,
    )
    workdir = storage.analysis_dir(analysis.id)
    try:
        upload_path = storage.subdir(analysis.id, "upload") / original_name
        analysis.file_size = _save(upload, upload_path)
        analysis.stored_path = str(upload_path)
        _check_magic(upload_path, ext)

        documents: list[Document] = []
        if ext in storage.ARCHIVES:
            extracted = extract_zip(
                upload_path, storage.subdir(analysis.id, "files"),
                max_files=settings.max_archive_files,
                max_unpacked_bytes=settings.max_archive_unpacked_mb * 1024 * 1024,
                max_depth=settings.max_archive_depth,
            )
            if not extracted:
                raise UploadRejected(400, "Архив пуст")
            for item in extracted:
                documents.append(Document(
                    id=uuid.uuid4(), analysis_id=analysis.id,
                    file_name=Path(item.relative_path).name[:255],
                    relative_path=item.relative_path,
                    file_path=str(item.stored_path),
                    file_type=item.ext.lstrip("."),
                    file_size=item.size,
                    status=initial_status if item.supported else "UNSUPPORTED",
                    analysis_mode=mode if item.supported else None,
                    error_message=None if item.supported else "Формат не поддерживается — файл не проверялся",
                ))
        else:
            documents.append(Document(
                id=uuid.uuid4(), analysis_id=analysis.id,
                file_name=original_name, relative_path=original_name,
                file_path=str(upload_path), file_type=ext.lstrip("."),
                file_size=analysis.file_size, status=initial_status,
                analysis_mode=mode,
            ))
    except ArchiveError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise UploadRejected(400, str(exc)) from exc
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise

    to_process = [d.id for d in documents if d.status == initial_status]
    if not to_process:
        analysis.analysis_status = "FAILED"
        analysis.progress = 100
        analysis.error_message = "В архиве нет документов поддерживаемых форматов (PDF, TXT, DOCX, DOC, RTF, изображения)"

    db.add(analysis)
    db.flush()
    db.add_all(documents)
    log_action(db, user.id, "ANALYSIS_CREATED", "analysis", analysis.id, {
        "file": original_name, "size": analysis.file_size, "documents": len(documents),
        "project": project.title if project else None, "project_id": str(project.id) if project else None,
        "analysis_mode": mode,
    })
    return analysis, to_process


def enqueue(document_ids: list[uuid.UUID]) -> None:
    from app.tasks import process_document

    for document_id in document_ids:
        process_document.delay(str(document_id))


def remove_files(analysis_id: uuid.UUID) -> None:
    shutil.rmtree(settings.storage_dir / str(analysis_id), ignore_errors=True)
