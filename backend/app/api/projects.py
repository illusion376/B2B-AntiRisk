"""Проекты — раздел «Документы» во фронтенде (Project, ProjectFile в frontend/lib/types.ts)."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.analyses import check_content_length, enqueue_documents, rerun
from app.api.deps import current_user, get_project_or_404, project_files_out, projects_out
from app.db import get_db
from app.models import Analysis, Document, Project, User
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate, RerunRequest, StartRequest, UploadError, UploadResult
from app.services import uploads
from app.services.analysis_modes import analysis_mode_or_422
from app.services.audit import log_action

router = APIRouter(prefix="/api/projects", tags=["Проекты"])

DUPLICATE_TITLE = "Проект с таким названием уже существует."


def _title_taken(db: Session, user: User, title: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(Project.id).where(Project.user_id == user.id, func.lower(Project.title) == title.lower())
    if exclude:
        query = query.where(Project.id != exclude)
    return db.scalar(query) is not None


def _one(db: Session, project: Project) -> ProjectOut:
    return projects_out(db, [project])[0]


@router.get("", response_model=list[ProjectOut], summary="Все проекты с файлами и статусами обработки")
def list_projects(
    q: str | None = Query(None, description="Поиск по названию проекта и именам файлов"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(Project).where(Project.user_id == user.id)
    if q:
        pattern = f"%{q.strip()}%"
        in_files = select(Analysis.project_id).where(Analysis.original_filename.ilike(pattern))
        query = query.where(Project.title.ilike(pattern) | Project.id.in_(in_files))
    return projects_out(db, list(db.scalars(query.order_by(Project.updated_at.desc()))))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="Новый проект")
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if _title_taken(db, user, body.title):
        raise HTTPException(409, DUPLICATE_TITLE)
    project = Project(user_id=user.id, title=body.title, description=body.description)
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:  # параллельное создание с тем же названием
        db.rollback()
        raise HTTPException(409, DUPLICATE_TITLE) from exc
    log_action(db, user.id, "PROJECT_CREATED", "project", project.id, {"title": project.title})
    db.commit()
    db.refresh(project)
    return _one(db, project)


@router.get("/{project_id}", response_model=ProjectOut, summary="Проект и его файлы")
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _one(db, get_project_or_404(db, project_id, user))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Переименовать проект / изменить описание")
def update_project(project_id: uuid.UUID, body: ProjectUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    project = get_project_or_404(db, project_id, user)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in changes and _title_taken(db, user, changes["title"], exclude=project.id):
        raise HTTPException(409, DUPLICATE_TITLE)
    for key, value in changes.items():
        setattr(project, key, value)
    log_action(db, user.id, "PROJECT_UPDATED", "project", project.id, {"title": project.title, "changes": list(changes)})
    db.commit()
    db.refresh(project)
    return _one(db, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить проект со всеми файлами")
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = get_project_or_404(db, project_id, user)
    analysis_ids = list(db.scalars(select(Analysis.id).where(Analysis.project_id == project.id)))
    log_action(db, user.id, "PROJECT_DELETED", "project", project.id, {"title": project.title})
    db.delete(project)
    db.commit()
    for analysis_id in analysis_ids:
        uploads.remove_files(analysis_id)


@router.post("/{project_id}/files", response_model=UploadResult, status_code=status.HTTP_202_ACCEPTED,
             summary="Загрузить один или несколько файлов в проект (PDF, TXT, ZIP, DOCX...)")
def upload_files(
    project_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(..., description="Можно несколько файлов; ZIP распаковывается"),
    law_type: Literal["AUTO", "44-FZ", "223-FZ"] = Form("AUTO"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Ошибка одного файла не отменяет загрузку остальных — как во фронтенде, ошибки возвращаются списком."""
    check_content_length(request)
    project = get_project_or_404(db, project_id, user)
    existing = {(a.original_filename, a.file_size) for a in project.analyses}

    accepted: list[Analysis] = []
    errors: list[UploadError] = []
    for upload in files:
        name = upload.filename or "файл"
        size = upload.size
        if size is not None and (name, size) in existing:
            errors.append(UploadError(name=name, detail="Этот файл уже добавлен в проект."))
            continue
        try:
            analysis, _ = uploads.create_analysis(db, user, upload, law_type, project, defer_processing=True)
        except uploads.UploadRejected as exc:
            errors.append(UploadError(name=name, detail=exc.detail))
            continue
        existing.add((analysis.original_filename, analysis.file_size))
        accepted.append(analysis)

    if accepted:
        project.updated_at = func.now()
    db.commit()
    return UploadResult(files=project_files_out(db, accepted), errors=errors)


@router.post("/{project_id}/start", status_code=status.HTTP_202_ACCEPTED,
             summary="Начать анализ загруженных, ещё не проверенных документов проекта")
def start_project(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user),
                  body: StartRequest | None = None):
    project = get_project_or_404(db, project_id, user)
    mode = analysis_mode_or_422(body.analysis_mode if body else None)
    # Блокировка и фильтр статуса защищают от повторной отправки при двойном клике
    # или одновременном запуске из нескольких вкладок.
    analyses = list(db.scalars(select(Analysis).where(
        Analysis.project_id == project.id, Analysis.analysis_status == "UPLOADED")
        .order_by(Analysis.id).with_for_update()))
    docs = list(db.scalars(select(Document).where(
        Document.analysis_id.in_([a.id for a in analyses]), Document.status == "UPLOADED")
        .order_by(Document.id).with_for_update())) if analyses else []
    if not docs:
        raise HTTPException(409, "Нет документов, ожидающих запуска анализа")
    for doc in docs:
        doc.status, doc.progress, doc.error_message = "QUEUED", 0, None
        doc.analysis_mode = mode
    for analysis in analyses:
        analysis.analysis_status, analysis.progress, analysis.error_message = "QUEUED", 0, None
        log_action(db, user.id, "ANALYSIS_STARTED", "analysis", analysis.id,
                   {"file": analysis.original_filename, "project": project.title, "analysis_mode": mode})
    project.updated_at = func.now()
    db.commit()
    enqueue_documents(db, docs)
    return {"documents": len(docs)}


@router.post("/{project_id}/rerun", status_code=status.HTTP_202_ACCEPTED,
             summary="Перепроверить все файлы проекта (например, после изменения правил)")
def rerun_project(project_id: uuid.UUID, body: RerunRequest | None = None, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    project = get_project_or_404(db, project_id, user)
    documents = rerun(db, user, list(project.analyses), body.rule_ids if body else None,
                      body.analysis_mode if body else None)
    return {"documents": documents}
