"""Анализ = один загруженный файл (документ или ZIP). Для интерфейса удобнее /api/projects,
эти эндпоинты остаются для статуса, SSE-прогресса, повторной проверки и загрузки без проекта."""
import json
import logging
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    analyses_out, counts_by_document, current_user, document_out, finding_out, get_analysis_or_404,
    get_project_or_404,
)
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Analysis, Document, RiskFinding, User, visible_findings
from app.schemas import AnalysisDetail, AnalysisPage, FindingOut, RerunRequest
from app.services import uploads
from app.services.audit import log_action
from app.services.pipeline import TERMINAL
from app.vocab import SEVERITY_FROM_API, parse_filter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analyses", tags=["Анализы"])


def analysis_detail(db: Session, analysis: Analysis) -> AnalysisDetail:
    base = analyses_out(db, [analysis])[0]
    docs = list(db.scalars(
        select(Document).where(Document.analysis_id == analysis.id)
        .order_by(func.coalesce(Document.relative_path, Document.file_name))
    ))
    counts = counts_by_document(db, [d.id for d in docs])
    return AnalysisDetail(**base.model_dump(), documents=[document_out(d, counts.get(d.id)) for d in docs])


def check_content_length(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes * 20:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Слишком большой запрос")


@router.post("", response_model=AnalysisDetail, status_code=status.HTTP_202_ACCEPTED,
             summary="Загрузить документ или ZIP-архив на проверку")
def create_analysis(
    request: Request,
    file: UploadFile = File(..., description=".zip, .pdf, .txt, .docx, .doc, .rtf, .odt или изображение, до 100 МБ"),
    law_type: Literal["AUTO", "44-FZ", "223-FZ"] = Form("AUTO"),
    title: str | None = Form(None),
    project_id: uuid.UUID | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    check_content_length(request)
    project = get_project_or_404(db, project_id, user) if project_id else None
    try:
        analysis, to_process = uploads.create_analysis(db, user, file, law_type, project, title)
    except uploads.UploadRejected as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    db.commit()
    start_processing(db, analysis, to_process)
    return analysis_detail(db, analysis)


def start_processing(db: Session, analysis: Analysis, document_ids: list[uuid.UUID]) -> None:
    try:
        uploads.enqueue(document_ids)
    except Exception as exc:  # брокер недоступен
        log.exception("Failed to enqueue analysis %s", analysis.id)
        analysis.analysis_status = "FAILED"
        analysis.error_message = "Очередь задач недоступна, повторите попытку позже"
        db.commit()
        raise HTTPException(503, analysis.error_message) from exc


@router.get("", response_model=AnalysisPage, summary="Все загруженные файлы пользователя")
def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Поиск по названию/имени файла"),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(Analysis).where(Analysis.user_id == user.id)
    if q:
        pattern = f"%{q}%"
        query = query.where(Analysis.title.ilike(pattern) | Analysis.original_filename.ilike(pattern))
    if status_filter:
        query = query.where(Analysis.analysis_status == status_filter.upper())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = list(db.scalars(query.order_by(Analysis.created_at.desc()).limit(limit).offset(offset)))
    return AnalysisPage(items=analyses_out(db, items), total=total or 0)


@router.get("/{analysis_id}", response_model=AnalysisDetail, summary="Статус файла и список документов (содержимое ZIP)")
def get_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return analysis_detail(db, get_analysis_or_404(db, analysis_id, user))


@router.get("/{analysis_id}/events", summary="Прогресс обработки в реальном времени (Server-Sent Events)")
def analysis_events(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_analysis_or_404(db, analysis_id, user)
    db.close()

    def stream():
        last_payload = None
        deadline = time.monotonic() + 30 * 60
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                analysis = session.get(Analysis, analysis_id)
                if analysis is None:
                    yield "event: error\ndata: {\"detail\": \"not found\"}\n\n"
                    return
                docs = session.execute(
                    select(Document.id, Document.status, Document.progress)
                    .where(Document.analysis_id == analysis_id)
                ).all()
                payload = json.dumps({
                    "id": str(analysis.id),
                    "status": analysis.analysis_status,
                    "progress": analysis.progress,
                    "risk_score": analysis.risk_score,
                    "documents": [{"id": str(d.id), "status": d.status, "progress": d.progress} for d in docs],
                }, ensure_ascii=False)
                finished = analysis.analysis_status in TERMINAL
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            else:
                yield ": keep-alive\n\n"
            if finished:
                yield "event: done\ndata: {}\n\n"
                return
            time.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{analysis_id}/findings", response_model=list[FindingOut], summary="Все замечания по всем документам файла")
def analysis_findings(
    analysis_id: uuid.UUID,
    severity: str | None = Query(None, description="critical, warning, low, ok (через запятую)"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    get_analysis_or_404(db, analysis_id, user)
    query = select(RiskFinding).where(RiskFinding.analysis_id == analysis_id, visible_findings())
    if severities := parse_filter(severity, SEVERITY_FROM_API, "severity"):
        query = query.where(RiskFinding.severity.in_(severities))
    return [finding_out(f) for f in db.scalars(query.order_by(RiskFinding.document_id, RiskFinding.sort_index))]


@router.post("/{analysis_id}/rerun", response_model=AnalysisDetail, status_code=status.HTTP_202_ACCEPTED,
             summary="Перепроверить документы правилами (после изменения правил) без повторного OCR")
def rerun_analysis(
    analysis_id: uuid.UUID,
    body: RerunRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    analysis = get_analysis_or_404(db, analysis_id, user)
    rerun(db, user, [analysis], body.rule_ids if body else None)
    return analysis_detail(db, analysis)


def rerun(db: Session, user: User, analyses: list[Analysis], rule_ids: list[str] | None) -> int:
    from app.tasks import reanalyze_document

    if any(a.analysis_status not in TERMINAL for a in analyses):
        raise HTTPException(409, "Проверка ещё выполняется")
    docs = list(db.scalars(select(Document).where(
        Document.analysis_id.in_([a.id for a in analyses]), Document.status == "COMPLETED")))
    if not docs:
        raise HTTPException(409, "Нет обработанных документов для повторной проверки")
    for doc in docs:
        doc.status, doc.progress = "ANALYZING", 70
    for analysis in analyses:
        if any(d.analysis_id == analysis.id for d in docs):
            analysis.analysis_status = "ANALYZING"
            log_action(db, user.id, "ANALYSIS_RERUN", "analysis", analysis.id,
                       {"file": analysis.original_filename, "rule_ids": rule_ids})
    db.commit()
    for doc in docs:
        reanalyze_document.delay(str(doc.id), rule_ids)
    return len(docs)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить файл и результаты проверки")
def delete_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    analysis = get_analysis_or_404(db, analysis_id, user)
    log_action(db, user.id, "ANALYSIS_DELETED", "analysis", analysis.id, {"file": analysis.original_filename})
    db.delete(analysis)
    db.commit()
    uploads.remove_files(analysis_id)
