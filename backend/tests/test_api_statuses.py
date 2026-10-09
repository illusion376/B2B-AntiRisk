"""Светофор и индекс риска не обещают успешную проверку без результатов."""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.api import deps
from app.models import Analysis, Document, Project
from app.schemas import SeverityCounts

NOW = datetime.now(timezone.utc)


def make_document(analysis_id, status="COMPLETED"):
    return Document(
        id=uuid.uuid4(), analysis_id=analysis_id, file_name="contract.pdf", relative_path="contract.pdf",
        file_path="contract.pdf", file_type="pdf", file_size=100, preview_path="contract.pdf",
        total_pages=1, is_scanned=False, status=status, progress=100, risk_score=99,
        law_type="44-FZ", ocr_pages=0, ocr_confidence=None, error_message=None,
        processing_ms=10, created_at=NOW, updated_at=NOW,
    )


def make_analysis(project_id=None, status="COMPLETED"):
    return Analysis(
        id=uuid.uuid4(), project_id=project_id, title="Contract", original_filename="contract.zip",
        file_type="zip", file_size=100, law_type="AUTO", analysis_status=status, progress=100,
        risk_score=99, rules_checked=99, error_message=None, created_at=NOW, updated_at=NOW,
        completed_at=NOW,
    )


def mock_counts(monkeypatch, analysis_counts=None, document_counts=None):
    monkeypatch.setattr(deps, "counts_by_analysis", lambda *_: analysis_counts or {})
    monkeypatch.setattr(deps, "counts_by_document", lambda *_: document_counts or {})


@pytest.mark.parametrize("status", ["UPLOADED", "QUEUED", "ANALYZING", "FAILED", "UNSUPPORTED", "COMPLETED"])
def test_document_without_visible_checks_has_no_traffic_light_or_score(status):
    result = deps.document_out(make_document(uuid.uuid4(), status))

    assert result.traffic_light is None
    assert result.risk_score is None
    assert result.rules_checked == 0


def test_dismissed_findings_still_count_as_completed_checks():
    result = deps.document_out(make_document(uuid.uuid4()), (SeverityCounts(), 3))

    assert result.traffic_light == "ok"
    assert result.risk_score == 0
    assert result.rules_checked == 3


def test_document_score_uses_visible_findings_after_rule_disabled():
    document = make_document(uuid.uuid4())
    result = deps.document_out(document, (SeverityCounts(warning=1, low=1), 2))

    assert result.traffic_light == "warning"
    assert result.risk_score == 13
    assert document.risk_score == 99  # сборка ответа не изменяет сохранённый результат


@pytest.mark.parametrize("critical,expected_light", [(0, "unknown"), (1, "critical")])
def test_incomplete_checks_never_produce_green_or_numeric_score(critical, expected_light):
    result = deps.document_out(make_document(uuid.uuid4()),
                               (SeverityCounts(critical=critical, unknown=1, ok=1), 3))

    assert result.traffic_light == expected_light
    assert result.risk_score is None
    assert result.counts.unknown == 1


def test_archive_does_not_hide_unknown_score_of_one_document(monkeypatch):
    analysis = make_analysis()
    known, unknown = make_document(analysis.id), make_document(analysis.id)
    mock_counts(monkeypatch, {analysis.id: (SeverityCounts(critical=1, unknown=1), 2)},
                {known.id: (SeverityCounts(critical=1), 1), unknown.id: (SeverityCounts(unknown=1), 1)})
    db = MagicMock()
    db.scalars.return_value = [known, unknown]

    result = deps.project_files_out(db, [analysis])[0]

    assert result.traffic_light == "critical"
    assert result.risk_score is None


@pytest.mark.parametrize("status", ["FAILED", "COMPLETED"])
def test_project_without_successful_checks_is_not_green(monkeypatch, status):
    project = Project(id=uuid.uuid4(), title="Test", description="", created_at=NOW, updated_at=NOW)
    analysis = make_analysis(project.id, status)
    document = make_document(analysis.id, status)
    mock_counts(monkeypatch)
    db = MagicMock()
    db.scalars.side_effect = [[analysis], [document]]

    result = deps.projects_out(db, [project])[0]

    assert result.traffic_light is None
    assert result.files[0].traffic_light is None
    assert result.files[0].risk_score is None


def test_analysis_and_project_file_share_filtered_counts_and_max_document_score(monkeypatch):
    analysis = make_analysis()
    docs = [make_document(analysis.id), make_document(analysis.id)]
    mock_counts(
        monkeypatch,
        {analysis.id: (SeverityCounts(warning=2), 1)},
        {doc.id: (SeverityCounts(warning=1), 1) for doc in docs},
    )
    db = MagicMock()
    db.scalars.return_value = docs

    file = deps.project_files_out(db, [analysis])[0]
    result = deps.analyses_out(db, [analysis])[0]

    assert file.risk_score == result.risk_score == 10  # max(10, 10), а не сумма рисков двух документов
    assert file.traffic_light == result.traffic_light == "warning"
    assert file.counts == result.counts == SeverityCounts(warning=2)
    assert file.rules_checked == result.rules_checked == 1
    assert result.documents_total == result.documents_supported == 2


def test_partially_failed_archive_does_not_claim_successful_full_check(monkeypatch):
    analysis = make_analysis()
    ready = make_document(analysis.id)
    failed = make_document(analysis.id, "FAILED")
    mock_counts(monkeypatch, {analysis.id: (SeverityCounts(ok=1), 1)},
                {ready.id: (SeverityCounts(ok=1), 1)})
    db = MagicMock()
    db.scalars.return_value = [ready, failed]

    result = deps.project_files_out(db, [analysis])[0]

    assert result.documents[0].traffic_light == "ok"
    assert result.traffic_light is None
    assert result.risk_score is None
