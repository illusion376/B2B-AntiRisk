import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_analysis_or_404, get_document_or_404
from app.api.documents import content_disposition
from app.db import get_db
from app.models import User
from app.schemas import ReportMode
from app.services import reports
from app.services.audit import log_action
from app.services.reports.data import collect

router = APIRouter(tags=["Отчёты"])

ModeParam = Query("detailed", description="brief | detailed | protocol | annotated")
FormatParam = Query("docx", description="docx | pdf | csv | json")


@router.get("/api/reports/modes", response_model=list[ReportMode], summary="Доступные режимы отчёта (для выпадающего списка)")
def report_modes():
    return reports.MODES


def _build(db: Session, user: User, analysis_id: uuid.UUID, document_id: uuid.UUID | None, mode: str, fmt: str,
           include_dismissed: bool) -> FileResponse:
    analysis = get_analysis_or_404(db, analysis_id, user)
    if mode == "annotated":
        fmt = "pdf"  # единственный формат для документа с пометками
    if analysis.analysis_status not in ("COMPLETED", "FAILED"):
        raise HTTPException(409, "Проверка ещё не завершена")
    data = collect(db, analysis, user, document_id, include_dismissed)
    try:
        report = reports.generate(data, mode, fmt)
    except reports.ReportError as exc:
        raise HTTPException(400, str(exc)) from exc
    log_action(db, user.id, "REPORT_DOWNLOADED", "analysis", analysis.id,
               {"mode": mode, "format": fmt, "document_id": str(document_id) if document_id else None})
    db.commit()
    return FileResponse(report.path, media_type=report.media_type,
                        headers={"Content-Disposition": content_disposition(report.filename)})


@router.get("/api/analyses/{analysis_id}/report", summary="Скачать отчёт по всему пакету (или по одному документу)")
def analysis_report(
    analysis_id: uuid.UUID,
    mode: Literal["brief", "detailed", "protocol", "annotated"] = ModeParam,
    format: Literal["docx", "pdf", "csv", "json"] = FormatParam,
    document_id: uuid.UUID | None = Query(None),
    include_dismissed: bool = Query(False, description="Включать отклонённые (ложные) замечания"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _build(db, user, analysis_id, document_id, mode, format, include_dismissed)


@router.get("/api/documents/{document_id}/report", summary="Скачать отчёт по документу (кнопка «Скачать отчёт»)")
def document_report(
    document_id: uuid.UUID,
    mode: Literal["brief", "detailed", "protocol", "annotated"] = ModeParam,
    format: Literal["docx", "pdf", "csv", "json"] = FormatParam,
    include_dismissed: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc = get_document_or_404(db, document_id, user)
    return _build(db, user, doc.analysis_id, doc.id, mode, format, include_dismissed)
