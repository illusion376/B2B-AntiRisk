"""Quality describes measured extraction and the actual run, never inferred accuracy."""
import os
import uuid

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.models import Document, DocumentPage
from app.services.document_quality import build_quality_snapshot, document_quality, page_quality
from app.services.extraction import PageContent


def extracted_page(number, *, ocr=False, confidence=None, error=None, text="Contract text"):
    return PageContent(
        page_number=number, width=595, height=842, text=text,
        is_ocr=ocr, ocr_confidence=confidence, ocr_error=error,
    )


def document(*, pages=None, threshold=80, **fields):
    values = dict(
        id=uuid.uuid4(), analysis_id=uuid.uuid4(), file_name="contract.pdf", status="COMPLETED",
        total_pages=len(pages) if pages is not None else 1,
        ocr_confidence=None, processing_ms=None, processing_kind=None, processing_sla_ms=None,
        error_message=None,
        quality_snapshot=build_quality_snapshot(pages, threshold) if pages is not None else None,
    )
    return Document(**(values | fields))


def stored_page(page):
    return DocumentPage(
        page_number=page.page_number, width=page.width, height=page.height,
        text=page.text, is_ocr=page.is_ocr, ocr_confidence=page.ocr_confidence,
    )


def test_native_text_has_no_invented_ocr_confidence():
    pages = [extracted_page(1), extracted_page(2)]
    doc = document(pages=pages)
    quality = document_quality(doc)

    assert quality.status == "native"
    assert quality.confidence is None
    assert quality.measured_ocr_pages == quality.ocr_pages == 0
    assert quality.native_pages == quality.total_pages == 2
    assert quality.ocr_percent == 0 and quality.native_percent == 100
    assert not quality.manual_review_required and not quality.review_pages
    page = page_quality(doc, stored_page(pages[0]))
    assert page.status == "native" and page.confidence is None
    assert not page.manual_review_required


def test_mixed_document_counts_pages_instead_of_diluting_confidence_with_native_text():
    pages = [extracted_page(1), extracted_page(2, ocr=True, confidence=82.5), extracted_page(3)]
    quality = document_quality(document(pages=pages))

    assert quality.status == "ok"
    assert quality.confidence == 82.5
    assert quality.measured_ocr_pages == quality.ocr_pages == 1
    assert quality.native_pages == 2 and quality.total_pages == 3
    assert quality.ocr_percent == 33.3 and quality.native_percent == 66.7
    assert not quality.manual_review_required


def test_high_average_cannot_hide_one_low_quality_page():
    pages = [extracted_page(n, ocr=True, confidence=confidence)
             for n, confidence in enumerate([99, 99, 79], 1)]
    doc = document(pages=pages)
    quality = document_quality(doc)

    assert quality.confidence == pytest.approx((99 + 99 + 79) / 3)
    assert quality.status == "low" and quality.manual_review_required
    assert [issue.page for issue in quality.review_pages] == [3]
    assert quality.review_pages[0].reason == "low_confidence"
    assert "Результат требует ручной проверки" in quality.warning
    assert page_quality(doc, stored_page(pages[0])).status == "ok"
    low_page = page_quality(doc, stored_page(pages[2]))
    assert low_page.status == "low" and low_page.confidence == 79
    assert low_page.confidence_threshold == 80 and low_page.manual_review_required
    assert "Результат требует ручной проверки" in low_page.warning


@pytest.mark.parametrize("confidence,threshold,status", [(80, 80, "ok"), (0, 80, "low"), (0, 0, "ok"), (100, 100, "ok")])
def test_threshold_is_inclusive_and_zero_confidence_is_a_measurement(confidence, threshold, status):
    quality = document_quality(document(pages=[extracted_page(1, ocr=True, confidence=confidence)], threshold=threshold))

    assert quality.status == status
    assert quality.confidence == confidence
    assert quality.measured_ocr_pages == 1
    assert quality.manual_review_required == (status == "low")


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), float("-inf"), -1, 101, True])
def test_unavailable_or_invalid_ocr_confidence_requires_manual_review(confidence):
    pages = [extracted_page(1, ocr=True, confidence=confidence)]
    doc = document(pages=pages)
    quality = document_quality(doc)

    assert quality.status == "unknown" and quality.confidence is None
    assert quality.measured_ocr_pages == 0 and quality.manual_review_required
    assert quality.ocr_pages == 1 and quality.native_pages == 0
    assert quality.review_pages[0].reason == "confidence_missing"
    page = page_quality(doc, stored_page(pages[0]))
    assert page.status == "unknown" and page.confidence is None and page.manual_review_required


@pytest.mark.parametrize("error,text,reason", [
    ("ocr_failed", "Native footer", "ocr_failed"),
    ("ocr_disabled", "Native footer", "ocr_disabled"),
    ("ocr_empty", "", "ocr_empty"),
    (None, " \n ", "ocr_empty"),
])
def test_unreadable_image_pages_remain_in_image_share_and_do_not_skew_average(error, text, reason):
    pages = [
        extracted_page(1),
        extracted_page(2, ocr=True, confidence=95),
        extracted_page(3, ocr=True, confidence=100, error=error, text=text),
    ]
    doc = document(pages=pages)
    quality = document_quality(doc)

    assert quality.status == "unknown" and quality.manual_review_required
    assert quality.confidence == 95 and quality.measured_ocr_pages == 1
    assert quality.ocr_pages == 2 and quality.native_pages == 1
    assert quality.ocr_percent == 66.7 and quality.native_percent == 33.3
    assert [(issue.page, issue.reason) for issue in quality.review_pages] == [(3, reason)]
    page = page_quality(doc, stored_page(pages[2]))
    assert page.status == "unknown" and page.reason == reason
    assert page.confidence is None and page.manual_review_required


def test_low_and_unknown_pages_are_both_preserved():
    quality = document_quality(document(pages=[
        extracted_page(1, ocr=True, confidence=70),
        extracted_page(2, ocr=True, error="ocr_failed", text=""),
    ]))

    assert quality.status == "low" and quality.manual_review_required
    assert [(issue.page, issue.status) for issue in quality.review_pages] == [(1, "low"), (2, "unknown")]


def test_empty_extraction_does_not_report_native_success_or_percentages():
    quality = document_quality(document(pages=[], status="FAILED"))

    assert quality.status == "unknown" and quality.manual_review_required
    assert quality.confidence is None
    assert quality.total_pages == quality.ocr_pages == quality.native_pages == 0
    assert quality.ocr_percent is None and quality.native_percent is None


def test_saved_threshold_is_used_after_server_configuration_changes(monkeypatch):
    pages = [extracted_page(1, ocr=True, confidence=85)]
    doc = document(pages=pages, threshold=90)
    snapshot_before = doc.quality_snapshot.copy()
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 70)
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 1)

    assert document_quality(doc).status == "low"
    assert document_quality(doc).confidence_threshold == 90
    assert page_quality(doc, stored_page(pages[0])).status == "low"
    assert doc.quality_snapshot == snapshot_before
    assert "processing_ms" not in doc.quality_snapshot
    assert "sla_status" not in doc.quality_snapshot


@pytest.mark.parametrize("snapshot", [None, [], {}, {"version": 1}, {"version": 2}, {"version": 1, "status": "invalid"},
                                      {"version": 1, "confidence": float("nan")}])
def test_legacy_or_unreadable_snapshot_never_claims_verified_quality(snapshot):
    doc = document(quality_snapshot=snapshot, total_pages=3, ocr_confidence=92.5, ocr_pages=1)
    quality = document_quality(doc)

    assert quality.status == "unknown" and quality.manual_review_required
    assert quality.confidence_threshold is None
    assert quality.total_pages == 3
    assert quality.ocr_percent is None and quality.native_percent is None
    assert "отсутствуют" in quality.warning
    page = page_quality(doc, stored_page(extracted_page(1, ocr=True, confidence=92.5)))
    assert page.status == "unknown" and page.reason == "quality_not_recorded"
    assert page.manual_review_required


@pytest.mark.parametrize("status", ["UPLOADED", "QUEUED", "CONVERTING", "OCR", "VECTORIZING", "ANALYZING"])
def test_active_run_does_not_expose_old_time_or_claim_sla_was_met(status):
    quality = document_quality(document(status=status, processing_kind="full", processing_ms=1_000,
                                        processing_sla_ms=2_000))

    assert quality.processing_ms is None and quality.sla_status == "not_measured"
    assert not quality.manual_review_required


@pytest.mark.parametrize("elapsed,limit,status,error,expected", [
    (999, 1_000, "COMPLETED", None, "within"),
    (1_000, 1_000, "COMPLETED", None, "within"),
    (1_001, 1_000, "COMPLETED", None, "exceeded"),
    (0, 1_000, "COMPLETED", None, "within"),
    (None, 1_000, "COMPLETED", None, "not_measured"),
    (500, None, "COMPLETED", None, "not_configured"),
    (500, 1_000, "FAILED", "OCR failed", "not_applicable"),
    (500, 1_000, "COMPLETED", "Some rules failed", "not_applicable"),
    (1_001, 1_000, "FAILED", "OCR failed", "exceeded"),
])
def test_full_run_sla_uses_saved_limit_and_requires_a_successful_check(elapsed, limit, status, error, expected):
    quality = document_quality(document(processing_kind="full", processing_ms=elapsed, processing_sla_ms=limit,
                                        status=status, error_message=error))

    assert quality.processing_ms == elapsed
    assert quality.sla_ms == limit
    assert quality.sla_status == expected


def test_reanalysis_time_cannot_be_compared_to_full_pipeline_sla():
    quality = document_quality(document(processing_kind="reanalysis", processing_ms=500, processing_sla_ms=1_000))

    assert quality.processing_kind == "reanalysis" and quality.processing_ms == 500
    assert quality.sla_status == "not_applicable"


def test_legacy_duration_without_a_recorded_kind_does_not_claim_sla_compliance():
    quality = document_quality(document(processing_ms=500, processing_sla_ms=1_000))

    assert quality.processing_kind is None and quality.sla_status == "not_measured"


@pytest.mark.parametrize("field,value", [
    ("ocr_quality_min_confidence", -0.1),
    ("ocr_quality_min_confidence", 100.1),
    ("ocr_quality_min_confidence", float("nan")),
    ("ocr_quality_min_confidence", float("inf")),
    ("document_processing_sla_seconds", 0),
    ("document_processing_sla_seconds", -1),
    ("document_processing_sla_seconds", 2_147_484),
    ("ocr_threads", 0),
])
def test_quality_configuration_rejects_impossible_thresholds_and_limits(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_quality_configuration_accepts_its_boundaries_and_optional_sla():
    for threshold in (0, 80, 100):
        config = Settings(_env_file=None, ocr_quality_min_confidence=threshold,
                          document_processing_sla_seconds=None)
        assert config.ocr_quality_min_confidence == threshold
        assert config.document_processing_sla_seconds is None
    assert Settings(_env_file=None, document_processing_sla_seconds=1).document_processing_sla_seconds == 1
    # An explicitly empty Compose value disables the operator-level limit.
    for value in ("", "   "):
        assert Settings(_env_file=None, document_processing_sla_seconds=value).document_processing_sla_seconds is None


def test_quality_defaults_allow_environment_overrides_and_explicit_disabled_sla(monkeypatch):
    fields = {"ocr_quality_min_confidence", "document_processing_sla_seconds"}
    for name in tuple(os.environ):
        if name.lower() in fields:
            monkeypatch.delenv(name)

    defaults = Settings(_env_file=None)
    assert defaults.ocr_quality_min_confidence == 95
    assert defaults.document_processing_sla_seconds == 120

    monkeypatch.setenv("OCR_QUALITY_MIN_CONFIDENCE", "87.5")
    monkeypatch.setenv("DOCUMENT_PROCESSING_SLA_SECONDS", "240")
    overrides = Settings(_env_file=None)
    assert overrides.ocr_quality_min_confidence == 87.5
    assert overrides.document_processing_sla_seconds == 240

    monkeypatch.setenv("DOCUMENT_PROCESSING_SLA_SECONDS", "")
    assert Settings(_env_file=None).document_processing_sla_seconds is None
