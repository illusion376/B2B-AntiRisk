"""User quality preferences use the existing profile API and affect actual worker runs."""
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import documents, system
from app.config import settings
from app.db import get_db
from app.models import Analysis, Base, Document, User
from app.services import pipeline
from app.services.document_quality import document_quality
from app.services.extraction import PageContent


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def sqlite_uuid(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def quality_preferences_workspace(tmp_path, monkeypatch, contract_pdf):
    engine = create_engine(f"sqlite:///{tmp_path / 'quality-preferences.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    owner, other = uuid.UUID(settings.default_user_id), uuid.uuid4()
    first_analysis, second_analysis = uuid.uuid4(), uuid.uuid4()
    first_document, second_document = uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as db:
        db.add_all([
            User(id=owner, email="quality-owner@example.test", full_name="Аналитик", company_name="Компания"),
            User(id=other, email="quality-other@example.test", full_name="Другой аналитик", company_name="Другая компания"),
            Analysis(id=first_analysis, user_id=owner, title="Первый договор", original_filename="first.pdf",
                     file_type="pdf", analysis_status="QUEUED"),
            Analysis(id=second_analysis, user_id=other, title="Второй договор", original_filename="second.pdf",
                     file_type="pdf", analysis_status="QUEUED"),
            Document(id=first_document, analysis_id=first_analysis, file_name="first.pdf", file_type="pdf",
                     file_path=str(contract_pdf), status="QUEUED", analysis_mode="keyword"),
            Document(id=second_document, analysis_id=second_analysis, file_name="second.pdf", file_type="pdf",
                     file_path=str(contract_pdf), status="QUEUED", analysis_mode="keyword"),
        ])

    def database():
        with sessions() as db:
            yield db

    @contextmanager
    def session():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 80)
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 120)
    monkeypatch.setattr(pipeline, "session_scope", session)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: clock.now))

    def extract(*_args):
        clock.now += 1
        return [PageContent(
            page_number=1, width=595, height=842, is_ocr=True, ocr_confidence=85,
            text="1. Условия договора\n1.1. Поставщик передаёт товар покупателю в течение тридцати рабочих дней.",
        )]

    def embed(texts):
        clock.now += 2
        return [[0.0] * 1024 for _ in texts]

    def evaluate(*_args, **_kwargs):
        clock.now += 4
        return []

    monkeypatch.setattr(pipeline, "_extract", extract)
    monkeypatch.setattr(pipeline, "embed_texts", embed)
    monkeypatch.setattr(pipeline, "evaluate_heuristic", evaluate)
    app = FastAPI()
    app.include_router(system.router)
    app.include_router(documents.router)
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, sessions=sessions, owner=owner, other=other,
            first_document=first_document, second_document=second_document, clock=clock,
        )
    engine.dispose()


def save_settings(workspace, confidence=90, seconds=5, user_id=None):
    payload = {"quality_settings": {"ocr_min_confidence": confidence, "processing_sla_seconds": seconds}}
    headers = {"X-User-Id": str(user_id)} if user_id is not None else {}
    response = workspace.client.patch("/api/users/me", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_unsaved_preferences_use_server_defaults_without_persisting_them(quality_preferences_workspace, monkeypatch):
    workspace = quality_preferences_workspace
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 73.5)
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 180)

    response = workspace.client.get("/api/users/me")

    assert response.status_code == 200
    assert response.json()["quality_settings"] == {"ocr_min_confidence": 73.5, "processing_sla_seconds": 180}
    with workspace.sessions() as db:
        assert db.get(User, workspace.owner).quality_settings is None
    monkeypatch.setattr(settings, "document_processing_sla_seconds", None)
    assert workspace.client.get("/api/users/me").json()["quality_settings"]["processing_sla_seconds"] is None


def test_preferences_patch_is_committed_without_overwriting_profile_or_other_users(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    before = workspace.client.get("/api/users/me").json()
    profile = save_settings(workspace, confidence=87.5, seconds=45)

    assert profile["quality_settings"] == {"ocr_min_confidence": 87.5, "processing_sla_seconds": 45}
    assert {key: value for key, value in profile.items() if key != "quality_settings"} == {
        key: value for key, value in before.items() if key != "quality_settings"
    }
    assert workspace.client.get("/api/users/me").json() == profile
    with workspace.sessions() as db:
        assert db.get(User, workspace.owner).quality_settings == profile["quality_settings"]
        assert db.get(User, workspace.other).quality_settings is None
    other = save_settings(workspace, confidence=75, seconds=300, user_id=workspace.other)
    assert other["quality_settings"]["ocr_min_confidence"] == 75
    assert workspace.client.get("/api/users/me").json() == profile


def test_profile_only_patch_preserves_quality_settings(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    selected = save_settings(workspace)["quality_settings"]

    response = workspace.client.patch("/api/users/me", json={"full_name": "  Иван Иванов  ", "company_name": " Новая компания "})

    assert response.status_code == 200
    assert response.json()["quality_settings"] == selected
    assert response.json()["full_name"] == "Иван Иванов" and response.json()["initials"] == "ИИ"
    assert response.json()["company_name"] == "Новая компания"
    assert workspace.client.get("/api/users/me").json()["quality_settings"] == selected


def test_explicit_null_sla_overrides_nonempty_server_default_and_survives_changes(quality_preferences_workspace, monkeypatch):
    workspace = quality_preferences_workspace
    save_settings(workspace, confidence=0, seconds=None)
    monkeypatch.setattr(settings, "ocr_quality_min_confidence", 100)
    monkeypatch.setattr(settings, "document_processing_sla_seconds", 60)

    body = workspace.client.get("/api/users/me").json()

    assert body["quality_settings"] == {"ocr_min_confidence": 0, "processing_sla_seconds": None}
    with workspace.sessions() as db:
        assert db.get(User, workspace.owner).quality_settings == body["quality_settings"]


def test_company_only_patch_can_clear_company_without_losing_name_or_settings(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    selected = save_settings(workspace)["quality_settings"]

    response = workspace.client.patch("/api/users/me", json={"company_name": None})

    assert response.status_code == 200
    assert response.json()["full_name"] == "Аналитик"
    assert response.json()["company_name"] is None
    assert response.json()["quality_settings"] == selected


@pytest.mark.parametrize("confidence,seconds", [(0, None), (100, 1), (79.96, 2_147_483)])
def test_quality_preferences_accept_valid_boundaries(quality_preferences_workspace, confidence, seconds):
    body = save_settings(quality_preferences_workspace, confidence=confidence, seconds=seconds)
    assert body["quality_settings"] == {"ocr_min_confidence": confidence, "processing_sla_seconds": seconds}


@pytest.mark.parametrize("payload", [
    {}, {"full_name": None}, {"full_name": ""}, {"full_name": "   "}, {"quality_settings": None},
    {"role": "ADMIN"}, {"quality_settings": {}},
    {"quality_settings": {"ocr_min_confidence": 80}},
    {"quality_settings": {"processing_sla_seconds": 30}},
    *[{"quality_settings": {"ocr_min_confidence": value, "processing_sla_seconds": 30}}
      for value in [-0.01, 100.01, None, "NaN", "Infinity", True]],
    *[{"quality_settings": {"ocr_min_confidence": 80, "processing_sla_seconds": value}}
      for value in [0, -1, 1.5, 2_147_484, True, "not a number"]],
    {"quality_settings": {"ocr_min_confidence": 80, "processing_sla_seconds": 30, "role": "ADMIN"}},
    {"full_name": "Изменённое имя", "quality_settings": {"ocr_min_confidence": -1, "processing_sla_seconds": 30}},
])
def test_invalid_partial_patch_does_not_modify_any_saved_field(quality_preferences_workspace, payload):
    workspace = quality_preferences_workspace
    before = save_settings(workspace)

    response = workspace.client.patch("/api/users/me", json=payload)

    assert response.status_code == 422, response.text
    assert workspace.client.get("/api/users/me").json() == before


def test_worker_uses_each_documents_owner_preferences(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    save_settings(workspace, confidence=90, seconds=5)
    save_settings(workspace, confidence=70, seconds=10, user_id=workspace.other)

    pipeline.process_document(workspace.first_document)
    pipeline.process_document(workspace.second_document)

    with workspace.sessions() as db:
        first, second = db.get(Document, workspace.first_document), db.get(Document, workspace.second_document)
        assert first.status == second.status == "COMPLETED"
        assert first.processing_ms == second.processing_ms == 7000
        assert first.quality_snapshot["confidence_threshold"] == 90
        assert second.quality_snapshot["confidence_threshold"] == 70
        assert first.quality_snapshot["status"] == "low" and second.quality_snapshot["status"] == "ok"
        assert first.processing_sla_ms == 5000 and second.processing_sla_ms == 10_000
        assert document_quality(first).sla_status == "exceeded"
        assert document_quality(second).sla_status == "within"


def test_worker_respects_explicit_no_time_limit_over_server_default(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    save_settings(workspace, confidence=90, seconds=None)

    pipeline.process_document(workspace.first_document)

    with workspace.sessions() as db:
        doc = db.get(Document, workspace.first_document)
        assert doc.processing_ms == 7000 and doc.processing_sla_ms is None
        assert document_quality(doc).sla_status == "not_configured"


def test_settings_changed_during_run_do_not_rewrite_its_selected_thresholds(quality_preferences_workspace, monkeypatch):
    workspace = quality_preferences_workspace
    save_settings(workspace, confidence=90, seconds=5)
    original_extract = pipeline._extract

    def update_during_extraction(*args):
        save_settings(workspace, confidence=70, seconds=100)
        return original_extract(*args)

    monkeypatch.setattr(pipeline, "_extract", update_during_extraction)

    pipeline.process_document(workspace.first_document)

    with workspace.sessions() as db:
        doc = db.get(Document, workspace.first_document)
        assert doc.quality_snapshot["confidence_threshold"] == 90
        assert doc.processing_sla_ms == 5000
        assert document_quality(doc).status == "low"
        assert document_quality(doc).sla_status == "exceeded"
    assert workspace.client.get("/api/users/me").json()["quality_settings"] == {
        "ocr_min_confidence": 70, "processing_sla_seconds": 100,
    }


def test_later_preference_updates_preserve_saved_document_assessment(quality_preferences_workspace):
    workspace = quality_preferences_workspace
    save_settings(workspace, confidence=90, seconds=5)
    pipeline.process_document(workspace.first_document)
    before = workspace.client.get(f"/api/documents/{workspace.first_document}").json()["quality"]

    save_settings(workspace, confidence=70, seconds=None)

    after = workspace.client.get(f"/api/documents/{workspace.first_document}").json()["quality"]
    assert after == before
    assert after["confidence_threshold"] == 90 and after["sla_ms"] == 5000
    assert after["status"] == "low" and after["sla_status"] == "exceeded"
