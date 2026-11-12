"""Rule-test uploads use real persistence and HTTP, without a broker or AI service."""
import io
import uuid
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import analyses, documents, history, projects, rules
from app.config import settings
from app.db import get_db
from app.models import Analysis, AuditLog, Base, Document, DocumentChunk, DocumentPage, Project, RiskFinding, RiskRule, User
from app.services import pipeline, uploads
from app.services.extraction import PageContent
from app.services.retrieval import RetrievedChunk


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def sqlite_uuid(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def rule_workspace(tmp_path, monkeypatch, contract_pdf):
    engine = create_engine(f"sqlite:///{tmp_path / 'rule-tests.db'}")

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("lower", 1, lambda value: value.lower() if value is not None else None,
                                   deterministic=True)

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner, other = uuid.UUID(settings.default_user_id), uuid.uuid4()
    with sessions.begin() as db:
        db.add_all([
            User(id=owner, email="rules@example.test", full_name="Проверяющий"),
            User(id=other, email="other@example.test", full_name="Другой пользователь"),
        ])

    def database():
        with sessions() as db:
            yield db

    @contextmanager
    def worker_database():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "files")
    monkeypatch.setattr(settings, "analysis_engine", "keyword")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(pipeline, "session_scope", worker_database)
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.0] * 1024 for _ in texts])
    analyze = MagicMock(wraps=pipeline.analyze_document)
    monkeypatch.setattr(pipeline, "analyze_document", analyze)
    queue = MagicMock()
    monkeypatch.setattr(uploads, "enqueue", queue)
    app = FastAPI()
    for router in (projects.router, analyses.router, documents.router, rules.router, history.router):
        app.include_router(router)
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=sessions, queue=queue, analyze=analyze,
                              owner=owner, other=other, pdf=contract_pdf)
    engine.dispose()


def upload(workspace, *, filename="contract.pdf", content=None, fields=None, user=None):
    return workspace.client.post(
        "/api/analyses", data={"purpose": "rule_test", **(fields or {})},
        files={"file": (filename, workspace.pdf.read_bytes() if content is None else content)},
        headers={"X-User-Id": str(user)} if user else {},
    )


def prepared(workspace):
    response = upload(workspace)
    assert response.status_code == 202, response.text
    result = response.json()
    document_id = uuid.UUID(result["documents"][0]["id"])
    pipeline.process_document(document_id)
    return result, document_id


def test_upload_lazily_reuses_hidden_project_and_excludes_it_from_normal_lists(rule_workspace):
    workspace = rule_workspace
    assert workspace.client.get("/api/projects?purpose=rule_test").json() == []
    with workspace.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0

    def check_committed(ids):
        with workspace.sessions() as db:
            doc = db.get(Document, ids[0])
            assert doc.status == "QUEUED"
            analysis = db.get(Analysis, doc.analysis_id)
            assert db.get(Project, analysis.project_id).is_rule_test

    workspace.queue.side_effect = check_committed
    first = upload(workspace)
    second = upload(workspace, filename="second.pdf")
    assert first.status_code == second.status_code == 202
    one, two = first.json(), second.json()
    assert one["project_id"] == two["project_id"]
    assert one["documents"][0]["file_name"] == "contract.pdf", "The [Тест] prefix belongs to presentation"
    assert one["documents"][0]["phase"] == "queued"
    assert workspace.queue.call_count == 2
    assert workspace.client.get("/api/projects").json() == []
    assert workspace.client.get("/api/analyses").json() == {"items": [], "total": 0}
    hidden = workspace.client.get("/api/projects?purpose=rule_test").json()
    assert len(hidden) == 1 and hidden[0]["is_rule_test"]
    assert {item["id"] for item in hidden[0]["files"]} == {one["id"], two["id"]}
    with workspace.sessions() as db:
        actions = list(db.scalars(select(AuditLog.action)))
        assert actions == ["RULE_TEST_DOCUMENT_UPLOADED", "RULE_TEST_DOCUMENT_UPLOADED"]


def test_test_projects_are_personal_and_existing_ownership_guards_apply(rule_workspace):
    workspace = rule_workspace
    own, other = upload(workspace).json(), upload(workspace, user=workspace.other).json()
    assert own["project_id"] != other["project_id"]
    headers = {"X-User-Id": str(workspace.other)}
    own_projects = workspace.client.get("/api/projects?purpose=rule_test").json()
    other_projects = workspace.client.get("/api/projects?purpose=rule_test", headers=headers).json()
    assert [item["id"] for item in own_projects] == [own["project_id"]]
    assert [item["id"] for item in other_projects] == [other["project_id"]]
    for path in (f"/api/projects/{own['project_id']}", f"/api/analyses/{own['id']}",
                 f"/api/documents/{own['documents'][0]['id']}"):
        assert workspace.client.get(path, headers=headers).status_code == 404
    denied = workspace.client.post("/api/rules/preview", headers=headers, json={
        "title": "Срок оплаты", "category": "Оплата", "severity": "warning",
        "document_id": own["documents"][0]["id"],
    })
    assert denied.status_code == 404


def test_hidden_project_does_not_reserve_an_ordinary_project_title(rule_workspace):
    workspace = rule_workspace
    uploaded = upload(workspace).json()
    hidden = workspace.client.get(f"/api/projects/{uploaded['project_id']}").json()
    normal = workspace.client.post("/api/projects", json={"title": hidden["title"]})
    assert normal.status_code == 201, normal.text
    assert normal.json()["is_rule_test"] is False
    assert workspace.client.post("/api/projects", json={"title": hidden["title"]}).status_code == 409
    assert [item["id"] for item in workspace.client.get("/api/projects").json()] == [normal.json()["id"]]
    assert upload(workspace).json()["project_id"] == uploaded["project_id"]


def test_database_allows_only_one_hidden_project_per_owner(rule_workspace):
    workspace = rule_workspace
    upload(workspace)
    with workspace.sessions() as db:
        db.add(Project(user_id=workspace.owner, title="Ещё один тестовый", is_rule_test=True))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Project).where(Project.is_rule_test.is_(True))) == 1


@pytest.mark.parametrize("filename,content,status_code", [
    ("contract.exe", b"Unsupported", 415),
    ("empty.txt", b"", 400),
    ("broken.pdf", b"This is not a PDF", 400),
])
def test_rejected_uploads_do_not_leave_a_hidden_project_or_queue_a_job(rule_workspace, filename, content, status_code):
    workspace = rule_workspace
    response = upload(workspace, filename=filename, content=content)
    assert response.status_code == status_code, response.text
    workspace.queue.assert_not_called()
    assert workspace.client.get("/api/projects?purpose=rule_test").json() == []
    with workspace.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Analysis)) == 0
    assert not settings.storage_dir.exists() or not list(settings.storage_dir.iterdir())


def test_rule_upload_rejects_archives_and_an_explicit_project(rule_workspace):
    workspace = rule_workspace
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as files:
        files.writestr("contract.txt", "Contract")
    assert upload(workspace, filename="bundle.zip", content=archive.getvalue()).status_code == 415
    assert upload(workspace, fields={"project_id": str(uuid.uuid4())}).status_code == 422
    assert upload(workspace, fields={"purpose": "unknown"}).status_code == 422
    workspace.queue.assert_not_called()
    assert workspace.client.get("/api/projects?purpose=rule_test").json() == []


def test_preparation_is_available_without_a_configured_analysis_model(rule_workspace, monkeypatch):
    monkeypatch.setattr(settings, "analysis_engine", "llm")
    response = upload(rule_workspace)
    assert response.status_code == 202, response.text
    doc_id = uuid.UUID(response.json()["documents"][0]["id"])
    pipeline.process_document(doc_id)
    rule_workspace.analyze.assert_not_called()
    document = rule_workspace.client.get(f"/api/documents/{doc_id}").json()
    assert document["status"] == "COMPLETED"
    assert document["analysis_mode"] is None and document["llm_model"] is None


def test_ordinary_upload_still_queues_full_analysis_without_creating_a_test_project(rule_workspace):
    workspace = rule_workspace
    response = upload(workspace, fields={"purpose": "analysis"})
    assert response.status_code == 202, response.text
    assert response.json()["project_id"] is None
    assert response.json()["documents"][0]["analysis_mode"] == "keyword"
    workspace.queue.assert_called_once()
    assert workspace.client.get("/api/analyses").json()["total"] == 1
    assert workspace.client.get("/api/projects?purpose=rule_test").json() == []


def test_hidden_project_cannot_start_full_analysis_through_other_endpoints(rule_workspace):
    workspace = rule_workspace
    data = upload(workspace).json()
    project, analysis, document = data["project_id"], data["id"], data["documents"][0]["id"]
    workspace.queue.reset_mock()
    for path in (f"/api/projects/{project}/start", f"/api/projects/{project}/rerun",
                 f"/api/analyses/{analysis}/rerun", f"/api/documents/{document}/reanalyze"):
        response = workspace.client.post(path)
        assert response.status_code == 409, (path, response.text)
    assert workspace.client.post(f"/api/projects/{project}/files", files={"files": ("new.txt", b"Contract")}).status_code == 409
    assert upload(workspace, fields={"purpose": "analysis", "project_id": project}).status_code == 409
    workspace.queue.assert_not_called()
    assert workspace.client.get(f"/api/analyses/{analysis}").json()["documents"][0]["status"] == "QUEUED"


def test_queue_failure_is_visible_in_test_documents_without_a_normal_completion_notification(rule_workspace):
    workspace = rule_workspace
    workspace.queue.side_effect = ConnectionError("Broker unavailable")
    response = upload(workspace)
    assert response.status_code == 503
    hidden = workspace.client.get("/api/projects?purpose=rule_test").json()[0]
    document = hidden["files"][0]["documents"][0]
    assert document["phase"] == "failed" and document["error_message"]
    assert hidden["processing_count"] == 0
    assert workspace.client.get("/api/history?actions=ANALYSIS_COMPLETED,ANALYSIS_FAILED").json() == []


def test_worker_prepares_pages_and_index_without_checking_rules_or_saving_findings(rule_workspace):
    workspace = rule_workspace
    with workspace.sessions.begin() as db:
        db.add(RiskRule(id="existing", title="Существующее правило", category="Оплата", severity="YELLOW",
                        description="Проверка", semantic_query="оплата", llm_prompt="Проверить"))
    data, doc_id = prepared(workspace)
    workspace.analyze.assert_not_called()
    with workspace.sessions() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "COMPLETED" and doc.progress == 100
        assert doc.preview_path and doc.quality_snapshot
        assert doc.risk_score is None and doc.processing_sla_ms is None
        assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == doc_id)) == 2
        assert db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)) > 0
        assert db.scalar(select(func.count()).select_from(RiskFinding)) == 0
        assert db.get(RiskRule, "existing").query_embedding is None
        assert db.get(Analysis, uuid.UUID(data["id"])).rules_checked == 0
        assert list(db.scalars(select(AuditLog.action))) == ["RULE_TEST_DOCUMENT_UPLOADED", "RULE_TEST_DOCUMENT_READY"]
    reopened = workspace.client.get("/api/projects?purpose=rule_test").json()[0]
    assert reopened["files"][0]["documents"][0]["phase"] == "ready"
    assert workspace.client.get("/api/history?actions=ANALYSIS_COMPLETED,ANALYSIS_FAILED").json() == []


def test_unreadable_test_document_keeps_diagnostics_and_does_not_run_rule_analysis(rule_workspace, monkeypatch):
    workspace = rule_workspace
    response = upload(workspace).json()
    doc_id = uuid.UUID(response["documents"][0]["id"])
    monkeypatch.setattr(pipeline, "_extract", lambda *args: [
        PageContent(page_number=1, width=595, height=842, is_ocr=True, ocr_error="ocr_empty"),
    ])
    pipeline.process_document(doc_id)
    workspace.analyze.assert_not_called()
    document = workspace.client.get(f"/api/documents/{doc_id}").json()
    assert document["phase"] == "failed" and "извлечь текст" in document["error_message"]
    assert document["quality"]["manual_review_required"]
    assert document["quality"]["review_pages"][0]["reason"] == "ocr_empty"
    actions = [item["action"] for item in workspace.client.get("/api/history").json()]
    assert "RULE_TEST_DOCUMENT_FAILED" in actions and "ANALYSIS_FAILED" not in actions


def test_ready_test_document_works_with_existing_preview_and_does_not_persist_the_draft(rule_workspace, monkeypatch):
    workspace = rule_workspace
    data, doc_id = prepared(workspace)

    def search(db, requested_id, *_args, rule_test_title, max_distance):
        assert requested_id == doc_id
        assert rule_test_title == "Срок оплаты" and max_distance <= settings.retrieval_max_distance
        return [RetrievedChunk(id=chunk.id, chunk_index=chunk.chunk_index, page_number=chunk.page_number,
                               page_end=chunk.page_end, clause_title=chunk.clause_title, content=chunk.content,
                               score=1.0, fts_hit=True)
                for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == requested_id))]

    evaluator = MagicMock(return_value=[])
    monkeypatch.setattr(rules, "hybrid_search", search)
    monkeypatch.setattr(rules, "evaluate_heuristic", evaluator)
    result = workspace.client.post("/api/rules/preview", json={
        "title": "Срок оплаты", "description": "Срок больше семи рабочих дней", "category": "Оплата",
        "severity": "warning", "document_id": str(doc_id),
    })
    assert result.status_code == 200, result.text
    assert result.json()["document_id"] == str(doc_id)
    assert result.json()["document_name"] == data["documents"][0]["file_name"]
    assert result.json()["fragments"]
    evaluator.assert_called_once()
    contexts = evaluator.call_args.args[0]
    assert len(contexts) == 1 and contexts[0].rule.title == "Срок оплаты"
    with workspace.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RiskRule)) == 0
        assert db.scalar(select(func.count()).select_from(RiskFinding)) == 0


def test_rule_preview_handles_llm_failure_with_the_existing_heuristic_fallback(rule_workspace, monkeypatch):
    monkeypatch.setattr(settings, "analysis_engine", "llm")
    monkeypatch.setattr(settings, "llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")
    remote = AsyncMock(side_effect=RuntimeError("Provider unavailable"))
    fallback = MagicMock(return_value=[])
    monkeypatch.setattr(rules, "evaluate_with_llm", remote)
    monkeypatch.setattr(rules, "evaluate_heuristic", fallback)
    response = rule_workspace.client.post("/api/rules/preview", json={
        "title": "Срок оплаты", "category": "Оплата", "severity": "warning",
        "custom_text": "Заказчик перечисляет оплату в течение сорока пяти рабочих дней после поставки.",
    })
    assert response.status_code == 200, response.text
    remote.assert_awaited_once()
    fallback.assert_called_once()
    assert response.json()["fragments"][0]["content"].startswith("Заказчик перечисляет оплату")
