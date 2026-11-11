import logging
import time
import uuid

from app.celery_app import celery_app
from app.services import pipeline
from app.services.analysis_modes import AnalysisModeError

log = logging.getLogger(__name__)

@celery_app.task(name="documents.process")
def process_document(document_id: str) -> None:
    pipeline.process_document(uuid.UUID(document_id))

@celery_app.task(name="documents.reanalyze")
def reanalyze_document(document_id: str, rule_ids: list[str] | None = None) -> None:
    """Повторная проверка правилами без OCR и векторизации (например, после добавления правила)."""
    doc_id = uuid.UUID(document_id)
    started = time.monotonic()
    try:
        pipeline.set_document(doc_id, status="ANALYZING", progress=70, error_message=None,
                              processing_ms=None, processing_kind="reanalysis", processing_sla_ms=None)
        pipeline.analyze_document(doc_id, rule_ids, started_at=started, processing_kind="reanalysis")
    except Exception as exc:
        log.exception("Reanalysis of %s failed", document_id)

        detail = str(exc) if isinstance(exc, (AnalysisModeError, pipeline.ProcessingError)) else type(exc).__name__
        pipeline.set_document(doc_id, status="COMPLETED", progress=100,
                              processing_ms=max(0, round((time.monotonic() - started) * 1000)),
                              processing_kind="reanalysis",
                              error_message=f"Повторная проверка не удалась: {detail}")
        raise
