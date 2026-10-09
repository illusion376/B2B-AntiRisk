"""Пайплайн обработки одного документа (выполняется в Celery-воркере).

CONVERTING -> OCR (извлечение текста / распознавание) -> VECTORIZING -> ANALYZING -> COMPLETED
Каждый этап коммитит статус и прогресс сразу, чтобы фронтенд видел их через API.
"""
import asyncio
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.models import Analysis, AuditLog, Document, DocumentChunk, DocumentPage, Project, RiskFinding, RiskRule
from app.services import storage
from app.services.analysis_modes import AnalysisModeError, resolve_analysis_mode
from app.services.analyzer import FindingDraft, RuleContext, evaluate_heuristic, evaluate_nli, evaluate_with_llm
from app.services.converter import ConversionError, to_pdf
from app.services.embeddings import EmbeddingError, embed_texts
from app.services.extraction import PageContent, extract_pages
from app.services.retrieval import hybrid_search
from app.services.scoring import risk_score
from app.services.structure import build_chunks, build_outline, detect_law_type, split_segments
from app.vocab import SEVERITY_ORDER

log = logging.getLogger(__name__)

TERMINAL = {"COMPLETED", "FAILED", "UNSUPPORTED"}
# Статус анализа в целом = самый «ранний» этап среди документов в работе
_STAGE_RANK = {"UPLOADED": -1, "QUEUED": 0, "CONVERTING": 1, "OCR": 1, "VECTORIZING": 2, "ANALYZING": 3}
_ANALYSIS_STAGE = {-1: "UPLOADED", 0: "QUEUED", 1: "OCR", 2: "VECTORIZING", 3: "ANALYZING"}
_SEVERITY_ORDER = {severity: i for i, severity in enumerate(SEVERITY_ORDER)}


class ProcessingError(RuntimeError):
    """Ошибка с понятным пользователю сообщением."""


# ---------- статусы ----------

def set_document(document_id: uuid.UUID, **fields) -> None:
    with session_scope() as db:
        db.execute(update(Document).where(Document.id == document_id).values(**fields))
        analysis_id = db.scalar(select(Document.analysis_id).where(Document.id == document_id))
        if analysis_id:
            refresh_analysis(db, analysis_id)


def refresh_analysis(db: Session, analysis_id: uuid.UUID) -> None:
    """Пересчитывает статус и прогресс анализа по его документам.

    Строка анализа блокируется (FOR UPDATE), чтобы параллельно завершающиеся документы
    не затёрли итог друг друга.
    """
    analysis = db.execute(
        select(Analysis).where(Analysis.id == analysis_id).with_for_update()
    ).scalar_one_or_none()
    if analysis is None:
        return
    docs = db.execute(
        select(Document.status, Document.progress, Document.risk_score)
        .where(Document.analysis_id == analysis_id, Document.status != "UNSUPPORTED")
    ).all()
    if not docs:
        analysis.analysis_status = "FAILED"
        analysis.progress = 100
        analysis.error_message = (
            "В загруженном файле нет документов поддерживаемых форматов (PDF, DOCX, DOC, RTF, изображения)"
        )
        analysis.completed_at = func.now()
        return

    previous_status = analysis.analysis_status
    active = [d for d in docs if d.status not in TERMINAL]
    analysis.progress = round(sum(100 if d.status in TERMINAL else d.progress for d in docs) / len(docs))
    if active:
        rank = min(_STAGE_RANK.get(d.status, 0) for d in active)
        analysis.analysis_status = _ANALYSIS_STAGE[rank]
        analysis.completed_at = None
        return

    completed = [d for d in docs if d.status == "COMPLETED"]
    if completed:
        analysis.analysis_status = "COMPLETED"
        analysis.error_message = None
        analysis.risk_score = None if any(d.risk_score is None for d in completed) else max(
            d.risk_score for d in completed
        )
        analysis.rules_checked = db.scalar(
            select(func.count(func.distinct(RiskFinding.rule_id))).where(RiskFinding.analysis_id == analysis_id)
        ) or 0
    else:
        analysis.analysis_status = "FAILED"
        analysis.error_message = "Не удалось обработать ни один документ"
    analysis.completed_at = func.now()
    if previous_status != analysis.analysis_status:
        _log_completion(db, analysis)


def _log_completion(db: Session, analysis: Analysis) -> None:
    """Запись в журнале — источник «Истории» и уведомлений во фронтенде."""
    counts = dict(db.execute(
        select(RiskFinding.severity, func.count()).where(RiskFinding.analysis_id == analysis.id)
        .group_by(RiskFinding.severity)
    ).all())
    project_title = db.scalar(select(Project.title).where(Project.id == analysis.project_id)) if analysis.project_id else None
    db.add(AuditLog(
        user_id=analysis.user_id,
        action="ANALYSIS_COMPLETED" if analysis.analysis_status == "COMPLETED" else "ANALYSIS_FAILED",
        entity_type="analysis",
        entity_id=analysis.id,
        details={
            "file": analysis.original_filename,
            "project": project_title,
            "project_id": str(analysis.project_id) if analysis.project_id else None,
            "rules": analysis.rules_checked,
            "critical": counts.get("RED", 0),
            "warning": counts.get("YELLOW", 0),
            "low": counts.get("LOW", 0),
            "error": analysis.error_message,
        },
    ))


# ---------- этапы ----------

def _extract(document_id: uuid.UUID, pdf_path: Path) -> list[PageContent]:
    last_update = 0.0

    def on_page(done: int, total: int) -> None:
        nonlocal last_update
        now = time.monotonic()
        if now - last_update > 1.0 or done == total:
            last_update = now
            set_document(document_id, progress=10 + round(40 * done / max(total, 1)))

    return extract_pages(pdf_path, on_page=on_page)


def _save_pages(db: Session, document_id: uuid.UUID, pages: list[PageContent]) -> None:
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    db.add_all(DocumentPage(
        document_id=document_id,
        page_number=p.page_number,
        width=p.width,
        height=p.height,
        text=p.text,
        words=p.words,
        is_ocr=p.is_ocr,
        ocr_confidence=p.ocr_confidence,
    ) for p in pages)


def ensure_rule_embeddings(db: Session, rules: list[RiskRule]) -> None:
    """Эмбеддинг semantic_query кэшируется в risk_rules и пересчитывается при смене модели или текста."""
    model_id = settings.embedding_model_id
    stale = [r for r in rules if r.query_embedding is None or r.embedding_model != model_id]
    if not stale:
        return
    vectors = embed_texts([r.semantic_query for r in stale])
    for rule, vector in zip(stale, vectors):
        rule.query_embedding = vector
        rule.embedding_model = model_id
    db.flush()


def applicable_rules(db: Session, law_type: str | None, rule_ids: list[str] | None = None) -> list[RiskRule]:
    query = select(RiskRule).where(RiskRule.is_active.is_(True)).order_by(RiskRule.sort_order, RiskRule.id)
    if law_type in ("44-FZ", "223-FZ"):
        query = query.where(RiskRule.law_type.in_(["ALL", law_type]))
    if rule_ids:
        query = query.where(RiskRule.id.in_(rule_ids))
    return list(db.scalars(query))


def analyze_document(document_id: uuid.UUID, rule_ids: list[str] | None = None) -> None:
    """Прогоняет правила по уже извлечённому и векторизованному документу и сохраняет замечания."""
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise ProcessingError("Документ не найден")
        # Старые строки без режима получают текущий default ровно при новом запуске.
        # Для поставленных API задач всегда используем сохранённый выбор пользователя.
        mode = resolve_analysis_mode(doc.analysis_mode)
        doc.analysis_mode = mode
        rules = applicable_rules(db, doc.law_type, rule_ids)
        ensure_rule_embeddings(db, rules)
        contexts = [
            RuleContext(rule, hybrid_search(db, doc.id, rule.semantic_query, list(rule.query_embedding),
                                            settings.retrieval_top_k))
            for rule in rules
        ]
        pages = [
            {"page_number": n, "words": w}
            for n, w in db.execute(
                select(DocumentPage.page_number, DocumentPage.words)
                .where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)
            )
        ]
        document_name, law_type, analysis_id = doc.file_name, doc.law_type, doc.analysis_id

    if mode == "llm":
        drafts = asyncio.run(evaluate_with_llm(contexts, pages, document_name, law_type))
    elif mode == "nli":
        drafts = evaluate_nli(contexts, pages)
    else:
        drafts = evaluate_heuristic(contexts, pages)


    with session_scope() as db:
        stmt = delete(RiskFinding).where(RiskFinding.document_id == document_id)
        if rule_ids:
            stmt = stmt.where(RiskFinding.rule_id.in_(rule_ids))
        db.execute(stmt)
        _save_findings(db, analysis_id, document_id, drafts)
        db.flush()
        _renumber(db, document_id)
        severities = db.scalars(
            select(RiskFinding.severity)
            .where(RiskFinding.document_id == document_id, RiskFinding.review_status != "DISMISSED")
        ).all()
        db.execute(update(Document).where(Document.id == document_id).values(
            risk_score=risk_score(severities), status="COMPLETED", progress=100, error_message=None,
        ))
        refresh_analysis(db, analysis_id)


def _save_findings(db: Session, analysis_id: uuid.UUID, document_id: uuid.UUID, drafts: list[FindingDraft]) -> None:
    for d in drafts:
        db.add(RiskFinding(
            analysis_id=analysis_id,
            document_id=document_id,
            rule_id=d.rule.id,
            severity=d.severity,
            category=d.rule.category,
            title=d.title,
            short_description=d.short_description,
            page_number=d.page_number,
            clause=d.clause[:255] if d.clause else None,
            exact_quote=d.exact_quote,
            comment=d.comment,
            counter_proposal=d.counter_proposal,
            legal_reference=d.rule.legal_reference,
            highlights=d.highlights,
            quote_verified=d.quote_verified,
            confidence=d.confidence,
            source=d.source,
        ))


def _renumber(db: Session, document_id: uuid.UUID) -> None:
    """Порядок как в макете: критические, затем «внимание», затем «без замечаний»; внутри — по документу."""
    rows = db.execute(
        select(RiskFinding, RiskRule.sort_order)
        .outerjoin(RiskRule, RiskRule.id == RiskFinding.rule_id)
        .where(RiskFinding.document_id == document_id)
    ).all()
    ordered = sorted(rows, key=lambda r: (
        _SEVERITY_ORDER.get(r[0].severity, 3),
        r[0].page_number if r[0].page_number is not None else 10**6,
        r[1] or 0,
    ))
    for index, (finding, _) in enumerate(ordered):
        finding.sort_index = index


def process_document(document_id: uuid.UUID) -> None:
    started = time.monotonic()
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            log.warning("Document %s not found", document_id)
            return
        analysis = db.get(Analysis, doc.analysis_id)
        source, analysis_id, analysis_law = Path(doc.file_path), doc.analysis_id, analysis.law_type

    try:
        # Проверяем и сохраняем режим до длительных конвертации/OCR (включая старые задания).
        with session_scope() as db:
            doc = db.get(Document, document_id)
            doc.analysis_mode = resolve_analysis_mode(doc.analysis_mode)
        set_document(document_id, status="CONVERTING", progress=5, error_message=None)
        preview_target = storage.subdir(analysis_id, "preview") / f"{document_id}.pdf"
        try:
            preview = to_pdf(source, preview_target)
        except ConversionError as exc:
            raise ProcessingError(str(exc)) from exc
        set_document(document_id, preview_path=str(preview), status="OCR", progress=10)

        pages = _extract(document_id, preview)
        full_text = "\n".join(p.text for p in pages)
        if len(full_text.strip()) < 50:
            raise ProcessingError("Не удалось извлечь текст из документа (пустой или нечитаемый скан)")

        segments = split_segments(pages)
        chunks = build_chunks(segments)
        law_type = analysis_law if analysis_law in ("44-FZ", "223-FZ") else detect_law_type(full_text)
        ocr_pages = [p for p in pages if p.is_ocr]
        confidences = [p.ocr_confidence for p in ocr_pages if p.ocr_confidence is not None]

        with session_scope() as db:
            _save_pages(db, document_id, pages)
            db.execute(update(Document).where(Document.id == document_id).values(
                total_pages=len(pages),
                is_scanned=bool(ocr_pages),
                ocr_pages=len(ocr_pages),
                ocr_confidence=round(sum(confidences) / len(confidences), 1) if confidences else None,
                outline=build_outline(segments),
                law_type=law_type,
                status="VECTORIZING",
                progress=55,
            ))
            refresh_analysis(db, analysis_id)

        try:
            vectors = embed_texts([c.embedding_text for c in chunks])
        except EmbeddingError as exc:
            raise ProcessingError(str(exc)) from exc

        with session_scope() as db:
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            db.add_all(DocumentChunk(
                analysis_id=analysis_id,
                document_id=document_id,
                chunk_index=c.index,
                page_number=c.page_start,
                page_end=c.page_end,
                clause_title=c.clause_title,
                content=c.content,
                embedding=v,
            ) for c, v in zip(chunks, vectors))
            db.execute(update(Document).where(Document.id == document_id).values(status="ANALYZING", progress=70))
            refresh_analysis(db, analysis_id)

        analyze_document(document_id)
        set_document(document_id, processing_ms=round((time.monotonic() - started) * 1000))
        log.info("Document %s processed in %.1fs", document_id, time.monotonic() - started)
    except (ProcessingError, AnalysisModeError) as exc:
        log.warning("Document %s failed: %s", document_id, exc)
        set_document(document_id, status="FAILED", error_message=str(exc))
    except Exception as exc:
        log.exception("Document %s failed", document_id)
        set_document(document_id, status="FAILED", error_message=f"Внутренняя ошибка обработки: {type(exc).__name__}")
        raise
