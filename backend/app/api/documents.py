import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import counts_by_document, current_user, document_out, finding_out, get_document_or_404
from app.db import get_db
from app.models import DocumentPage, RiskFinding, User, visible_findings
from app.schemas import (
    DocumentOut, DocumentUpdate, FindingGroup, FindingsResponse, OutlineSection, PageContent, SearchResponse,
)
from app.services import pdf_tools
from app.services.audit import log_action
from app.services.search import search_pages
from app.services.structure import page_sections
from app.vocab import (
    REVIEW_FROM_API, SEVERITY_FROM_API, SEVERITY_GROUP_LABELS, SEVERITY_ORDER, SEVERITY_TO_API, parse_filter,
)

router = APIRouter(prefix="/api/documents", tags=["Документы"])


def content_disposition(filename: str, inline: bool = False) -> str:
    kind = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "ignore").decode() or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _pages_words(db: Session, document_id: uuid.UUID) -> list[dict]:
    return [
        {"page_number": n, "words": w}
        for n, w in db.execute(select(DocumentPage.page_number, DocumentPage.words)
                               .where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number))
    ]


@router.get("/{document_id}", response_model=DocumentOut, summary="Карточка документа: статус, страницы, светофор")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    return document_out(doc, counts_by_document(db, [doc.id]).get(doc.id))


@router.patch("/{document_id}", response_model=DocumentOut, summary="Переименовать документ")
def rename_document(document_id: uuid.UUID, body: DocumentUpdate, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    old_name = doc.file_name
    new_name = body.file_name
    suffix = Path(old_name).suffix
    if suffix and not new_name.lower().endswith(suffix.lower()):
        new_name += suffix  # расширение сохраняем, как фронтенд («.pdf» вне поля ввода)
    doc.file_name = new_name[:255]
    if doc.relative_path:
        parent = str(Path(doc.relative_path).parent)
        doc.relative_path = doc.file_name if parent in ("", ".") else f"{parent}/{doc.file_name}"
    if doc.analysis.file_type != "zip":  # одиночный файл: имя файла в проекте = имя документа
        doc.analysis.original_filename = doc.file_name
    log_action(db, user.id, "DOCUMENT_RENAMED", "document", doc.id, {"from": old_name, "to": doc.file_name})
    db.commit()
    return document_out(doc, counts_by_document(db, [doc.id]).get(doc.id))


@router.get("/{document_id}/file", summary="PDF документа (docx/txt и сканы уже приведены к PDF)")
def get_preview(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    if not doc.preview_path or not Path(doc.preview_path).exists():
        raise HTTPException(409, "Документ ещё обрабатывается — превью пока недоступно")
    name = f"{Path(doc.file_name).stem}.pdf"
    return FileResponse(doc.preview_path, media_type="application/pdf",
                        headers={"Content-Disposition": content_disposition(name, inline=True)})


@router.get("/{document_id}/original", summary="Скачать исходный файл")
def get_original(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    if not Path(doc.file_path).exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(doc.file_path, media_type="application/octet-stream",
                        headers={"Content-Disposition": content_disposition(doc.file_name)})


@router.get("/{document_id}/pages/{page_number}/thumbnail", summary="Миниатюра страницы (PNG) для панели «Страницы»",
            response_class=Response, responses={200: {"content": {"image/png": {}}}})
def get_thumbnail(
    document_id: uuid.UUID,
    page_number: int,
    width: int = Query(160, ge=40, le=1200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc = get_document_or_404(db, document_id, user)
    if not doc.preview_path:
        raise HTTPException(409, "Документ ещё обрабатывается")
    try:
        path = pdf_tools.thumbnail(Path(doc.preview_path), doc.analysis_id, doc.id, page_number, width)
    except IndexError as exc:
        raise HTTPException(404, "Нет такой страницы") from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


_SPACES = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACES.sub(" ", text.lower().replace("ё", "е")).strip()


@router.get("/{document_id}/pages/{page_number}", response_model=PageContent,
            summary="Текст страницы разделами и пунктами с привязкой замечаний (аналог getPageSections)")
def get_page(document_id: uuid.UUID, page_number: int, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    page = db.scalar(select(DocumentPage).where(
        DocumentPage.document_id == document_id, DocumentPage.page_number == page_number))
    if page is None:
        raise HTTPException(404, "Нет такой страницы")
    texts = db.execute(select(DocumentPage.page_number, DocumentPage.text)
                       .where(DocumentPage.document_id == document_id, DocumentPage.page_number <= page_number)
                       .order_by(DocumentPage.page_number)).all()
    sections = page_sections([(n, t) for n, t in texts], page_number)

    # Привязка замечаний к абзацам: по номеру пункта, иначе по началу цитаты
    findings = db.scalars(select(RiskFinding).where(
        RiskFinding.document_id == document_id, RiskFinding.page_number == page_number,
        RiskFinding.severity != "GREEN", visible_findings())).all()
    paragraphs = [p for s in sections for p in s["paragraphs"]]
    for p in paragraphs:
        p["finding_ids"] = []
    for f in findings:
        target = next((p for p in paragraphs if f.clause and p["clause"] == f.clause), None)
        if target is None and f.exact_quote:
            probe = _norm(f.exact_quote)[:60]
            target = next((p for p in paragraphs if probe and probe in _norm(p["text"])), None)
        if target is not None:
            target["finding_ids"].append(f.id)

    return PageContent(page=page_number, total_pages=doc.total_pages, width=page.width, height=page.height,
                       is_ocr=page.is_ocr, ocr_confidence=page.ocr_confidence, sections=sections)


@router.get("/{document_id}/outline", response_model=list[OutlineSection], summary="Оглавление (вкладка «Навигация»)")
def get_outline(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return get_document_or_404(db, document_id, user).outline or []


@router.get("/{document_id}/search", response_model=SearchResponse, summary="Поиск по тексту документа (в т. ч. по сканам)")
def search_document(
    document_id: uuid.UUID,
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    get_document_or_404(db, document_id, user)
    hits, total = search_pages(_pages_words(db, document_id), q, limit)
    return SearchResponse(query=q, total=total, hits=hits)


@router.get("/{document_id}/findings", response_model=FindingsResponse,
            summary="Замечания документа по группам светофора с фильтрами (категория, уровень, статус, поиск)")
def document_findings(
    document_id: uuid.UUID,
    severity: str | None = Query(None, description="critical, warning, low, ok (через запятую)"),
    category: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status", description="unseen, accepted, dismissed (через запятую)"),
    q: str | None = Query(None, description="Поиск по тексту замечания"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    get_document_or_404(db, document_id, user)
    base = select(RiskFinding).where(RiskFinding.document_id == document_id, visible_findings())
    categories = sorted({c for c in db.scalars(base.with_only_columns(RiskFinding.category).distinct()) if c})
    by_status = dict(db.execute(
        select(RiskFinding.review_status, func.count())
        .where(RiskFinding.document_id == document_id, RiskFinding.severity != "GREEN", visible_findings())
        .group_by(RiskFinding.review_status)
    ).all())

    query = base
    if severities := parse_filter(severity, SEVERITY_FROM_API, "severity"):
        query = query.where(RiskFinding.severity.in_(severities))
    if category:
        query = query.where(RiskFinding.category == category)
    if statuses := parse_filter(status_filter, REVIEW_FROM_API, "status"):
        query = query.where(RiskFinding.review_status.in_(statuses))
    if q:
        pattern = f"%{q}%"
        query = query.where(
            RiskFinding.title.ilike(pattern) | RiskFinding.comment.ilike(pattern)
            | RiskFinding.exact_quote.ilike(pattern) | RiskFinding.short_description.ilike(pattern)
        )
    items = [finding_out(f) for f in db.scalars(query.order_by(RiskFinding.sort_index))]

    groups = []
    for sev in SEVERITY_ORDER:
        api_sev = SEVERITY_TO_API[sev]
        group_items = [f for f in items if f.severity == api_sev]
        groups.append(FindingGroup(severity=api_sev, label=SEVERITY_GROUP_LABELS[sev], count=len(group_items),
                                   items=group_items))
    return FindingsResponse(
        document_id=document_id, total=len(items), groups=groups, categories=categories,
        statuses={
            "unseen": by_status.get("NEW", 0),
            "accepted": by_status.get("CONFIRMED", 0) + by_status.get("RESOLVED", 0),
            "dismissed": by_status.get("DISMISSED", 0),
        },
    )


@router.post("/{document_id}/reanalyze", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED,
             summary="Перепроверить документ правилами без повторного OCR")
def reanalyze(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.tasks import reanalyze_document

    doc = get_document_or_404(db, document_id, user)
    if doc.status != "COMPLETED":
        raise HTTPException(409, "Документ ещё не обработан")
    doc.status, doc.progress = "ANALYZING", 70
    doc.analysis.analysis_status = "ANALYZING"
    log_action(db, user.id, "DOCUMENT_REANALYZE", "document", doc.id, {"file": doc.file_name})
    db.commit()
    reanalyze_document.delay(str(doc.id))
    return document_out(doc)
