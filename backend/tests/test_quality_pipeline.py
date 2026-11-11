"""Quality must survive real persistence, worker failures and the existing APIs."""
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import documents
from app.config import settings
from app.db import get_db
from app.models import Analysis, Base, Document, DocumentPage, User
from app.services import pipeline
from app.services.document_quality import document_quality
from app.services.extraction import PageContent
from app.tasks import reanalyze_document


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def sqlite_uuid(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def quality_workspace(tmp_path, monkeypatch, contract_pdf):
    engine = create_engine(f"sqlite:///{tmp_path / 'quality.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    owner, analysis_id, doc_id = uuid.UUID(settings.default_user_id), uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as db:
        db.add(User(id=owner, email="quality@example.test", full_name="Проверяющий"))
        db.add(Analysis(id=analysis_id, user_id=owner, title="Проверка", original_filename="contract.pdf",
                        file_type="pdf", analysis_status="QUEUED"))
        db.add(Document(id=doc_id, analysis_id=analysis_id, file_name="contract.pdf", file_type="pdf",
                        file_path=str(contract_pdf), status="QUEUED", analysis_mode="keyword"))

    @contextmanager
    def session():
        with sessions.begin() as db:
            yield db

    def database():
        with sessions() as db:
            yield db

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(pipeline, "session_scope", session)
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 10)
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 80)

    def embed(texts):
        clock.now += 3
        return [[0.0] * 1024 for _ in texts]

    def evaluate(*args, **kwargs):
        clock.now += 4
        return []

    monkeypatch.setattr(pipeline, "embed_texts", embed)
    monkeypatch.setattr(pipeline, "evaluate_heuristic", evaluate)
    app = FastAPI()
    app.include_router(documents.router)
    app.dependency_overrides[get_db] = database
    yield SimpleNamespace(sessions=sessions, clock=clock, id=doc_id, client=TestClient(app))
    engine.dispose()


def test_success_commits_quality_and_elapsed_with_completed_status(quality_workspace, monkeypatch):
    workspace = quality_workspace
    extract = pipeline._extract

    def timed_extract(*args):
        pages = extract(*args)
        workspace.clock.now += 2
        return pages

    monkeypatch.setattr(pipeline, "_extract", timed_extract)
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "COMPLETED" and doc.processing_ms == 9000
        assert doc.processing_kind == "full" and doc.processing_sla_ms == 10_000
        assert len(list(db.scalars(select(DocumentPage)))) == 2
        quality = document_quality(doc)
        assert quality.status == "native" and quality.confidence is None
        assert quality.sla_status == "within"

    # Existing APIs, including a second read after a worker commit, expose the same snapshot.
    body = workspace.client.get(f"/api/documents/{workspace.id}").json()
    assert body["quality"]["processing_ms"] == body["processing_ms"] == 9000
    assert body["quality"]["native_percent"] == 100
    page = workspace.client.get(f"/api/documents/{workspace.id}/pages/1").json()
    assert page["quality"]["status"] == "native"
    assert page["quality"]["confidence"] is None


@pytest.mark.parametrize("reason", ["ocr_failed", "ocr_empty", "ocr_disabled"])
def test_unreadable_document_keeps_pages_preview_and_quality_after_failure(quality_workspace, monkeypatch, reason):
    workspace = quality_workspace

    def unreadable(*args):
        workspace.clock.now += 2
        return [PageContent(page_number=1, width=595, height=842, is_ocr=True, ocr_error=reason)]

    monkeypatch.setattr(pipeline, "_extract", unreadable)
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "FAILED" and doc.processing_ms == 2000
        assert doc.progress == 100 and doc.preview_path
        assert doc.total_pages == doc.ocr_pages == 1 and doc.is_scanned
        assert doc.quality_snapshot["review_pages"][0]["reason"] == reason
        assert list(db.scalars(select(DocumentPage)))[0].is_ocr
        assert document_quality(doc).sla_status == "not_applicable"

    response = workspace.client.get(f"/api/documents/{workspace.id}/pages/1")
    assert response.status_code == 200
    assert response.json()["quality"]["manual_review_required"]
    assert response.json()["quality"]["reason"] == reason
    assert workspace.client.get(f"/api/documents/{workspace.id}/file").status_code == 200


def test_error_after_extraction_preserves_quality_and_measures_failed_run(quality_workspace, monkeypatch):
    workspace = quality_workspace

    def fail_embedding(*args):
        workspace.clock.now += 11
        raise pipeline.EmbeddingError("Index unavailable")

    monkeypatch.setattr(pipeline, "embed_texts", fail_embedding)
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "FAILED" and doc.processing_ms == 11_000
        assert doc.quality_snapshot["status"] == "native"
        assert document_quality(doc).sla_status == "exceeded"
        assert len(list(db.scalars(select(DocumentPage)))) == 2


def test_reanalysis_replaces_time_but_keeps_original_extraction_snapshot(quality_workspace, monkeypatch):
    from app import tasks

    workspace = quality_workspace
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        before = db.get(Document, workspace.id).quality_snapshot
    monkeypatch.setattr(tasks, "time", SimpleNamespace(monotonic=lambda: workspace.clock.now))
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 95)
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 1)
    reanalyze_document.run(str(workspace.id))
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "COMPLETED" and doc.processing_ms == 4000
        assert doc.quality_snapshot == before
        assert doc.processing_kind == "reanalysis"
        assert document_quality(doc).sla_status == "not_applicable"
        assert document_quality(doc).confidence_threshold == 80


def test_failed_reanalysis_retains_diagnostics_and_never_reuses_old_time(quality_workspace, monkeypatch):
    from app import tasks

    workspace = quality_workspace
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        before = db.get(Document, workspace.id).quality_snapshot
    monkeypatch.setattr(tasks, "time", SimpleNamespace(monotonic=lambda: workspace.clock.now))

    def fail(*args, **kwargs):
        workspace.clock.now += 2
        raise RuntimeError("unavailable")

    monkeypatch.setattr(pipeline, "analyze_document", fail)
    with pytest.raises(RuntimeError):
        reanalyze_document.run(str(workspace.id))
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "COMPLETED" and "Повторная проверка не удалась" in doc.error_message
        assert doc.processing_ms == 2000 and doc.processing_kind == "reanalysis"
        assert doc.quality_snapshot == before
        assert document_quality(doc).sla_status == "not_applicable"


def test_rerun_api_resets_previous_time_before_scheduling(quality_workspace, monkeypatch):
    workspace = quality_workspace
    pipeline.process_document(workspace.id)
    observed = []

    def enqueue(_db, docs, *args):
        with workspace.sessions() as db:
            doc = db.get(Document, docs[0].id)
            observed.append((doc.status, doc.processing_ms, doc.processing_kind, doc.quality_snapshot))

    monkeypatch.setattr(documents, "enqueue_documents", enqueue)
    response = workspace.client.post(f"/api/documents/{workspace.id}/reanalyze", json={"analysis_mode": "keyword"})
    assert response.status_code == 202, response.text
    assert observed[0][:3] == ("ANALYZING", None, "reanalysis")
    assert observed[0][3] is not None
    assert response.json()["quality"]["processing_ms"] is None


def test_full_retry_clears_old_quality_even_if_conversion_fails(quality_workspace, monkeypatch):
    workspace = quality_workspace
    pipeline.process_document(workspace.id)

    def failed_conversion(*args):
        workspace.clock.now += 1
        raise pipeline.ConversionError("Could not convert")

    monkeypatch.setattr(pipeline, "to_pdf", failed_conversion)
    pipeline.process_document(workspace.id)
    with workspace.sessions() as db:
        doc = db.get(Document, workspace.id)
        assert doc.status == "FAILED" and doc.processing_ms == 1000
        assert doc.quality_snapshot is None
        assert document_quality(doc).status == "unknown"
        assert document_quality(doc).manual_review_required
