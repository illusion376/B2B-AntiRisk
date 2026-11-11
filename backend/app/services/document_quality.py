"""One quality policy for existing document/page APIs and all report formats.

Persist a sparse snapshot at extraction time: reading a project must not fetch
every page of every document. Confidence applies to OCR only. Native text does
not receive an invented 100% score; old runs without a snapshot remain unknown.
"""
import math
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.config import settings
from app.schemas import DocumentQuality, PageQuality, PageQualityIssue, QualitySettings

if TYPE_CHECKING:
    from app.models import Document, DocumentPage, User
    from app.services.extraction import PageContent

_REASONS = {
    "ocr_failed": "Не удалось распознать страницу",
    "ocr_disabled": "Страница требует распознавания, но OCR отключён",
    "ocr_empty": "OCR не обнаружил читаемого текста",
    "confidence_missing": "Уверенность распознавания страницы неизвестна",
}
_MANUAL_REVIEW = "Результат требует ручной проверки"
_TERMINAL = {"COMPLETED", "FAILED"}


def user_quality_settings(user: "User | None") -> QualitySettings:
    """Resolve the saved personal policy once; null SLA explicitly means no limit."""
    saved = getattr(user, "quality_settings", None)
    if isinstance(saved, dict):
        try:
            return QualitySettings.model_validate(saved)
        except ValidationError:
            # Older or malformed stored settings must not break the profile or a worker.
            pass
    return QualitySettings(
        ocr_min_confidence=settings.ocr_quality_min_confidence,
        processing_sla_seconds=settings.document_processing_sla_seconds,
    )


def valid_confidence(value: float | None) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100:
        return float(value)
    return None


def build_quality_snapshot(pages: list["PageContent"], threshold: float) -> dict:
    """Count all image pages, including failed/skipped OCR; never dilute a bad page."""
    issues: list[PageQualityIssue] = []
    measured: list[float] = []
    ocr_pages = 0
    for page in pages:
        if not page.is_ocr:
            continue
        ocr_pages += 1
        confidence = valid_confidence(page.ocr_confidence)
        reason = page.ocr_error
        if not reason and not page.text.strip():
            reason = "ocr_empty"
        if reason:
            confidence = None
        elif confidence is None:
            reason = "confidence_missing"
        else:
            measured.append(confidence)
            if confidence < threshold:
                reason = "low_confidence"
        if reason:
            message = (f"Уверенность OCR {confidence:g}% ниже порога {threshold:g}%"
                       if reason == "low_confidence" else _REASONS.get(reason, _REASONS["confidence_missing"]))
            issues.append(PageQualityIssue(
                page=page.page_number, status="low" if reason == "low_confidence" else "unknown",
                confidence=confidence, reason=reason, warning=f"{message}. {_MANUAL_REVIEW}",
            ))

    total = len(pages)
    ocr_percent = round(ocr_pages * 100 / total, 1) if total else None
    status = ("low" if any(p.status == "low" for p in issues) else "unknown" if issues or not total
              else "ok" if ocr_pages else "native")
    quality = DocumentQuality(
        status=status, confidence_threshold=threshold,
        confidence=sum(measured) / len(measured) if measured else None,
        total_pages=total, ocr_pages=ocr_pages, native_pages=total - ocr_pages,
        ocr_percent=ocr_percent, native_percent=round(100 - ocr_percent, 1) if ocr_percent is not None else None,
        measured_ocr_pages=len(measured), review_pages=issues, manual_review_required=bool(issues) or not total,
        warning=(f"Есть страницы с низким или неизвестным качеством распознавания. {_MANUAL_REVIEW}"
                 if issues else f"Страницы документа не извлечены. {_MANUAL_REVIEW}" if not total else None),
    )
    fields = quality.model_dump(mode="json", exclude={"processing_ms", "processing_kind", "sla_ms", "sla_status"})
    return {"version": 1, **fields}


def _snapshot_quality(doc: "Document") -> DocumentQuality | None:
    snapshot = getattr(doc, "quality_snapshot", None)
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        return None
    required = {"status", "confidence_threshold", "total_pages", "ocr_pages", "native_pages",
                "measured_ocr_pages", "review_pages", "manual_review_required"}
    if not required.issubset(snapshot):
        return None
    try:
        quality = DocumentQuality.model_validate(snapshot)
    except ValidationError:
        return None
    if (quality.confidence_threshold is None
            or quality.ocr_pages + quality.native_pages != quality.total_pages
            or quality.measured_ocr_pages > quality.ocr_pages
            or any(p.page > quality.total_pages for p in quality.review_pages)):
        return None
    return quality


def document_quality(doc: "Document") -> DocumentQuality:
    quality = _snapshot_quality(doc)
    terminal = doc.status in _TERMINAL
    if quality is None:
        quality = DocumentQuality(
            total_pages=max(doc.total_pages or 0, 0),
            confidence=valid_confidence(doc.ocr_confidence),
            manual_review_required=terminal,
            warning=(f"Данные о качестве этого запуска отсутствуют. {_MANUAL_REVIEW}" if terminal else None),
        )
    kind = getattr(doc, "processing_kind", None)
    quality.processing_kind = kind if kind in ("full", "reanalysis") else None
    elapsed = doc.processing_ms
    quality.processing_ms = elapsed if terminal and isinstance(elapsed, int) and elapsed >= 0 else None
    limit = getattr(doc, "processing_sla_ms", None)
    quality.sla_ms = limit if isinstance(limit, int) and limit > 0 else None
    if quality.processing_kind == "reanalysis":
        quality.sla_status = "not_applicable"
    elif quality.processing_ms is None or quality.processing_kind is None:
        quality.sla_status = "not_measured"
    elif quality.sla_ms is None:
        quality.sla_status = "not_configured"
    elif quality.processing_ms > quality.sla_ms:
        quality.sla_status = "exceeded"
    elif doc.status != "COMPLETED" or doc.error_message:
        # A fast failed or partial check must never appear as a successful SLA check.
        quality.sla_status = "not_applicable"
    else:
        quality.sla_status = "within"
    return quality


def page_quality(doc: "Document", page: "DocumentPage") -> PageQuality:
    quality = _snapshot_quality(doc)
    confidence = valid_confidence(page.ocr_confidence) if page.is_ocr else None
    if quality is None:
        return PageQuality(
            confidence=confidence, manual_review_required=True, reason="quality_not_recorded",
            warning=f"Качество этой страницы не зафиксировано. {_MANUAL_REVIEW}",
        )
    issue = next((p for p in quality.review_pages if p.page == page.page_number), None)
    if issue:
        return PageQuality(
            status=issue.status, confidence=issue.confidence, confidence_threshold=quality.confidence_threshold,
            manual_review_required=True, warning=issue.warning, reason=issue.reason,
        )
    return PageQuality(
        status="ok" if page.is_ocr else "native", confidence=confidence,
        confidence_threshold=quality.confidence_threshold,
    )
