"""Восстановление пользовательских операций, когда брокер не принимает задания."""
import uuid
from unittest.mock import MagicMock, call

import pytest
from fastapi import HTTPException

from app.api import analyses, documents, projects
from app.models import Analysis, Document, Project, User


@pytest.fixture
def queue(monkeypatch):
    from app.tasks import reanalyze_document

    initial = MagicMock()
    repeated = MagicMock()
    monkeypatch.setattr(analyses.uploads, "enqueue", initial)
    monkeypatch.setattr(reanalyze_document, "delay", repeated)
    refresh = MagicMock()
    monkeypatch.setattr(analyses, "refresh_analysis", refresh)
    monkeypatch.setattr(documents, "refresh_analysis", refresh)
    return initial, repeated, refresh


def make_document(analysis_id, status, **kwargs):
    return Document(id=uuid.uuid4(), analysis_id=analysis_id, status=status,
                    file_name="contract.pdf", progress=70 if status == "ANALYZING" else 0, **kwargs)


def test_initial_queue_failure_marks_documents_failed_and_attempts_every_job(queue):
    initial, _, refresh = queue
    initial.side_effect = ConnectionError("broker unavailable")
    analysis = Analysis(id=uuid.uuid4(), analysis_status="FAILED")
    docs = [make_document(analysis.id, "QUEUED") for _ in range(2)]
    db = MagicMock()
    db.get.return_value = analysis

    with pytest.raises(HTTPException) as error:
        analyses.enqueue_documents(db, docs)

    assert error.value.status_code == 503
    assert all(doc.status == "FAILED" and doc.progress == 100 for doc in docs)
    assert all(doc.error_message == analyses.QUEUE_UNAVAILABLE for doc in docs)
    assert initial.call_args_list == [call([doc.id]) for doc in docs]
    refresh.assert_called_once_with(db, analysis.id)
    db.commit.assert_called_once()


def test_partial_queue_failure_preserves_accepted_jobs_and_continues(queue):
    _, repeated, _ = queue
    repeated.side_effect = [None, ConnectionError("broker unavailable"), None]
    analysis = Analysis(id=uuid.uuid4(), analysis_status="ANALYZING")
    docs = [make_document(analysis.id, "ANALYZING", risk_score=37) for _ in range(3)]
    db = MagicMock()
    db.get.return_value = analysis

    with pytest.raises(HTTPException):
        analyses.enqueue_documents(db, docs, ["payment_delay"])

    assert [doc.status for doc in docs] == ["ANALYZING", "COMPLETED", "ANALYZING"]
    assert docs[1].risk_score == 37
    assert docs[1].error_message == analyses.QUEUE_UNAVAILABLE
    assert repeated.call_args_list == [call(str(doc.id), ["payment_delay"]) for doc in docs]
    db.delete.assert_not_called()  # прежние результаты остаются доступными


def test_rerun_reprocesses_failed_files_and_only_reanalyzes_completed_files(queue):
    initial, repeated, _ = queue
    analysis = Analysis(id=uuid.uuid4(), analysis_status="FAILED", original_filename="contract.zip")
    failed = make_document(analysis.id, "FAILED", error_message="old failure")
    completed = make_document(analysis.id, "COMPLETED")
    user = User(id=uuid.uuid4())
    db = MagicMock()
    db.scalars.return_value = [failed, completed]

    assert analyses.rerun(db, user, [analysis], None) == 2

    assert failed.status == "QUEUED" and failed.progress == 0 and failed.error_message is None
    assert completed.status == "ANALYZING" and completed.progress == 70
    initial.assert_called_once_with([failed.id])
    repeated.assert_called_once_with(str(completed.id), None)


def test_rerun_rejects_in_progress_analysis_without_scheduling(queue):
    initial, repeated, _ = queue
    analysis = Analysis(id=uuid.uuid4(), analysis_status="ANALYZING")

    with pytest.raises(HTTPException) as error:
        analyses.rerun(MagicMock(), User(id=uuid.uuid4()), [analysis], None)

    assert error.value.status_code == 409
    initial.assert_not_called()
    repeated.assert_not_called()


def test_document_reanalysis_failure_restores_completed_document(queue, monkeypatch):
    _, repeated, _ = queue
    repeated.side_effect = ConnectionError("broker unavailable")
    analysis = Analysis(id=uuid.uuid4(), analysis_status="COMPLETED")
    doc = make_document(analysis.id, "COMPLETED", risk_score=37)
    monkeypatch.setattr(documents, "get_document_or_404", lambda *_: doc)
    db = MagicMock()
    db.get.return_value = analysis

    with pytest.raises(HTTPException) as error:
        documents.reanalyze(doc.id, db, User(id=uuid.uuid4()))

    assert error.value.status_code == 503
    assert doc.status == "COMPLETED" and doc.progress == 100 and doc.risk_score == 37
    assert doc.error_message == analyses.QUEUE_UNAVAILABLE


def test_batch_upload_reports_queue_error_and_still_schedules_later_files(monkeypatch):
    project = Project(id=uuid.uuid4(), title="Test")
    project.analyses = []
    user = User(id=uuid.uuid4())
    accepted = [Analysis(id=uuid.uuid4(), original_filename=f"contract-{i}.pdf") for i in range(2)]
    uploads = [MagicMock(filename=item.original_filename, size=10) for item in accepted]
    jobs = [[uuid.uuid4()] for _ in accepted]
    create = MagicMock(side_effect=list(zip(accepted, jobs)))
    enqueue = MagicMock(side_effect=[HTTPException(503, analyses.QUEUE_UNAVAILABLE), None])
    monkeypatch.setattr(projects, "get_project_or_404", lambda *_: project)
    monkeypatch.setattr(projects.uploads, "create_analysis", create)
    monkeypatch.setattr(projects, "start_processing", enqueue)
    monkeypatch.setattr(projects, "project_files_out", lambda *_: [])
    db = MagicMock()
    request = MagicMock(headers={})

    result = projects.upload_files(project.id, request, uploads, "AUTO", db, user)

    assert len(result.errors) == 1
    assert result.errors[0].name == accepted[0].original_filename
    assert result.errors[0].detail == analyses.QUEUE_UNAVAILABLE
    assert enqueue.call_args_list == [call(db, item, ids) for item, ids in zip(accepted, jobs)]
