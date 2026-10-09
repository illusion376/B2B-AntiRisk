"""A selected analysis engine survives queueing and never silently becomes another engine."""
import io
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import analyses, documents, projects
from app.api.deps import current_user
from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import Analysis, Document, Project, User
from app.services import analysis_modes, pipeline, uploads


@pytest.fixture
def mode_settings(monkeypatch):
    config = Settings(_env_file=None, analysis_engine="auto", heuristic_engine="keyword", llm_base_url=None, llm_api_key="test-key")
    monkeypatch.setattr(analysis_modes, "settings", config)
    monkeypatch.setattr(pipeline, "settings", config)
    return config


@pytest.mark.parametrize("engine,url,heuristic,expected", [
    ("auto", None, "nli", "nli"),
    ("auto", "  ", "keyword", "keyword"),
    ("auto", "http://provider/v1", "nli", "llm"),
    ("keyword", "http://provider/v1", "nli", "keyword"),
    ("nli", "http://provider/v1", "keyword", "nli"),
])
def test_config_resolves_legacy_auto_and_explicit_modes(mode_settings, engine, url, heuristic, expected):
    mode_settings.analysis_engine = engine
    mode_settings.llm_base_url = url
    mode_settings.heuristic_engine = heuristic
    assert analysis_modes.default_analysis_mode() == expected
    if expected == "nli":
        with pytest.raises(analysis_modes.AnalysisModeError, match="NLI-модель отключена"):
            analysis_modes.resolve_analysis_mode()
    else:
        assert analysis_modes.resolve_analysis_mode() == expected


def test_invalid_environment_engine_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, analysis_engine="typo")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, heuristic_engine="typo")


@pytest.mark.parametrize("field", ["llm_concurrency", "llm_timeout_s", "llm_max_tokens", "retrieval_top_k"])
def test_invalid_engine_limits_are_rejected(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_blank_model_is_unavailable_for_explicit_llm_default(mode_settings):
    mode_settings.llm_base_url = "http://provider/v1"
    mode_settings.llm_model = "  "
    mode_settings.analysis_engine = "llm"
    assert analysis_modes.capabilities().default_mode == "llm"
    assert not analysis_modes.capabilities().modes[0].available
    with pytest.raises(analysis_modes.AnalysisModeError):
        analysis_modes.resolve_analysis_mode()


@pytest.mark.parametrize("requested,code", [("llm", "analysis_mode_unavailable"), ("auto", "invalid_analysis_mode"),
                                            ("", "invalid_analysis_mode"), ("other", "invalid_analysis_mode")])
def test_unavailable_or_invalid_mode_is_structured_422(mode_settings, requested, code):
    with pytest.raises(HTTPException) as error:
        analysis_modes.analysis_mode_or_422(requested)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == code
    assert error.value.detail["analysis_mode"] == requested
    assert error.value.detail["message"]


def test_explicit_llm_default_is_not_downgraded_when_unconfigured(mode_settings):
    mode_settings.analysis_engine = "llm"
    assert analysis_modes.capabilities().default_mode == "llm"
    with pytest.raises(analysis_modes.AnalysisModeError):
        analysis_modes.resolve_analysis_mode()


def test_public_capabilities_have_no_provider_url_or_key(mode_settings):
    mode_settings.llm_base_url = "http://private-provider/v1"
    mode_settings.llm_api_key = "secret-api-key"
    mode_settings.llm_model = "configured-model"
    response = TestClient(app).get("/api/analysis-modes")
    assert response.status_code == 200
    body = response.json()
    assert body["default_mode"] == "llm"
    assert body["configured_model"] == "configured-model"
    assert {mode["id"]: mode["available"] for mode in body["modes"]} == {
        "llm": True, "keyword": True,
    }
    assert "private-provider" not in response.text and "secret-api-key" not in response.text
    mode_settings.llm_base_url = None
    response = TestClient(app).get("/api/analysis-modes")
    assert "configured_model" not in response.json()
    assert response.json()["modes"][0]["available"] is False


@pytest.fixture
def api_client(monkeypatch, mode_settings):
    db = MagicMock()
    user = User(id=uuid.uuid4())
    analysis = Analysis(id=uuid.uuid4(), analysis_status="COMPLETED", original_filename="contract.txt")
    doc = Document(id=uuid.uuid4(), analysis_id=analysis.id, status="COMPLETED", analysis_mode="keyword")
    project = Project(id=uuid.uuid4(), title="Test")
    project.analyses = [analysis]
    monkeypatch.setattr(documents, "get_document_or_404", lambda *_: doc)
    monkeypatch.setattr(projects, "get_project_or_404", lambda *_: project)
    monkeypatch.setattr(analyses, "get_analysis_or_404", lambda *_: analysis)
    enqueue = MagicMock()
    monkeypatch.setattr(analyses, "enqueue_documents", enqueue)
    monkeypatch.setattr(documents, "enqueue_documents", enqueue)
    monkeypatch.setattr(projects, "enqueue_documents", enqueue)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: user
    try:
        yield TestClient(app), db, doc, enqueue
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("requested", ["llm", "nli"])
@pytest.mark.parametrize("path", ["projects/{id}/start", "projects/{id}/rerun", "analyses/{id}/rerun",
                                  "documents/{id}/reanalyze"])
def test_api_rejects_unavailable_modes_before_mutation_or_enqueue(api_client, path, requested):
    client, db, doc, enqueue = api_client
    response = client.post("/api/" + path.format(id=uuid.uuid4()), json={"analysis_mode": requested})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "analysis_mode_unavailable"
    assert doc.status == "COMPLETED" and doc.analysis_mode == "keyword"
    db.commit.assert_not_called()
    enqueue.assert_not_called()


def test_standalone_upload_rejects_llm_before_creating_files(api_client, monkeypatch):
    client, db, _, enqueue = api_client
    create = MagicMock()
    monkeypatch.setattr(uploads, "create_analysis", create)
    response = client.post("/api/analyses", data={"analysis_mode": "llm"},
                           files={"file": ("contract.txt", b"contract text", "text/plain")})
    assert response.status_code == 422
    create.assert_not_called()
    db.commit.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.parametrize("body", [None, {"analysis_mode": "keyword"}])
def test_project_start_accepts_optional_body_and_persists_before_enqueue(api_client, monkeypatch, body):
    client, db, doc, enqueue = api_client
    doc.status, doc.analysis_mode = "UPLOADED", None
    analysis = Analysis(id=doc.analysis_id, analysis_status="UPLOADED", original_filename="contract.txt")
    db.scalars.side_effect = [[analysis], [doc]]

    def on_enqueue(session, docs):
        assert docs == [doc]
        assert doc.analysis_mode == "keyword"
        assert doc.status == "QUEUED"
        db.commit.assert_called_once()

    enqueue.side_effect = on_enqueue
    response = client.post(f"/api/projects/{uuid.uuid4()}/start", **({"json": body} if body else {}))
    assert response.status_code == 202
    assert response.json() == {"documents": 1}
    enqueue.assert_called_once()


def test_batch_rerun_sets_same_mode_on_failed_and_completed_docs(mode_settings, monkeypatch):
    analysis = Analysis(id=uuid.uuid4(), analysis_status="COMPLETED", original_filename="contract.zip")
    docs = [Document(id=uuid.uuid4(), analysis_id=analysis.id, status=status, analysis_mode="nli")
            for status in ("FAILED", "COMPLETED")]
    db = MagicMock()
    db.scalars.return_value = docs
    monkeypatch.setattr(analyses, "refresh_analysis", MagicMock())

    def on_enqueue(session, queued, rule_ids):
        assert queued == docs and rule_ids == ["rule-a"]
        assert [d.analysis_mode for d in docs] == ["keyword", "keyword"]
        assert [d.status for d in docs] == ["QUEUED", "ANALYZING"]
        db.commit.assert_called_once()

    enqueue = MagicMock(side_effect=on_enqueue)
    monkeypatch.setattr(analyses, "enqueue_documents", enqueue)
    assert analyses.rerun(db, User(id=uuid.uuid4()), [analysis], ["rule-a"], "keyword") == 2
    enqueue.assert_called_once()


@pytest.mark.parametrize("stored,default,expected", [
    ("keyword", "llm", "keyword"), ("nli", "keyword", "nli"), ("llm", "keyword", "llm"),
    (None, "keyword", "keyword"),
])
def test_worker_dispatches_persisted_engine(mode_settings, monkeypatch, stored, default, expected):
    mode_settings.analysis_engine = default
    mode_settings.llm_base_url = "http://provider/v1"
    doc = Document(id=uuid.uuid4(), analysis_id=uuid.uuid4(), file_name="contract.txt", analysis_mode=stored)
    db = MagicMock()
    db.get.return_value = doc
    db.scalars.return_value.all.return_value = []

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(pipeline, "session_scope", session)
    monkeypatch.setattr(pipeline, "applicable_rules", lambda *_: [])
    for name in ("ensure_rule_embeddings", "_save_findings", "_renumber", "refresh_analysis"):
        monkeypatch.setattr(pipeline, name, MagicMock())
    evaluators = {"llm": AsyncMock(return_value=[]), "nli": MagicMock(return_value=[]),
                  "keyword": MagicMock(return_value=[])}
    for name, mode in (("evaluate_with_llm", "llm"), ("evaluate_nli", "nli"), ("evaluate_heuristic", "keyword")):
        monkeypatch.setattr(pipeline, name, evaluators[mode])
    if expected == "nli":
        with pytest.raises(analysis_modes.AnalysisModeError, match="NLI-модель отключена"):
            pipeline.analyze_document(doc.id)
        for evaluate in evaluators.values():
            evaluate.assert_not_called()
        db.execute.assert_not_called()
        return
    pipeline.analyze_document(doc.id)
    assert doc.analysis_mode == expected
    for mode, evaluate in evaluators.items():
        assert evaluate.call_count == (1 if mode == expected else 0)


def test_worker_cannot_silently_fallback_from_persisted_llm(mode_settings, monkeypatch):
    doc = Document(id=uuid.uuid4(), analysis_mode="llm")
    db = MagicMock()
    db.get.return_value = doc

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(pipeline, "session_scope", session)
    nli, keyword = MagicMock(), MagicMock()
    monkeypatch.setattr(pipeline, "evaluate_nli", nli)
    monkeypatch.setattr(pipeline, "evaluate_heuristic", keyword)
    with pytest.raises(analysis_modes.AnalysisModeError):
        pipeline.analyze_document(doc.id)
    nli.assert_not_called()
    keyword.assert_not_called()
    db.execute.assert_not_called()


@pytest.mark.parametrize("deferred,engine,requested,expected", [
    (True, "llm", None, None), (False, "keyword", None, "keyword"), (False, "nli", "keyword", "keyword"),
])
def test_uploaded_documents_persist_mode_only_when_selected(mode_settings, monkeypatch, tmp_path,
                                                           deferred, engine, requested, expected):
    from fastapi import UploadFile
    from app.services import storage

    mode_settings.analysis_engine = engine
    mode_settings.storage_dir = tmp_path
    monkeypatch.setattr(storage, "settings", mode_settings)
    monkeypatch.setattr(uploads, "settings", mode_settings)
    db = MagicMock()
    analysis, _ = uploads.create_analysis(db, User(id=uuid.uuid4()),
                                          UploadFile(filename="contract.txt", file=io.BytesIO(b"contract text")),
                                          defer_processing=deferred, analysis_mode=requested)
    saved = db.add_all.call_args.args[0]
    assert len(saved) == 1
    assert saved[0].analysis_mode == expected
    assert saved[0].status == ("UPLOADED" if deferred else "QUEUED")
    assert analysis.analysis_status == saved[0].status
