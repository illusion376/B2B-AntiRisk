"""Загрузка и ручной запуск через HTTP с настоящими транзакциями, без брокера/LLM."""
import io
import uuid
import zipfile
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import projects
from app.config import settings
from app.db import get_db
from app.models import Analysis, Base, Document, DocumentPage, Project, RiskFinding, User
from app.services import uploads


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def sqlite_uuid(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        # SQLite lower() only handles ASCII; production PostgreSQL also folds Cyrillic.
        connection.create_function("lower", 1, lambda value: value.lower() if value is not None else None, deterministic=True)

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        db.add(User(id=uuid.UUID(settings.default_user_id), email="analyst@example.test", full_name="Analyst"))
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "files")
    queue = MagicMock()
    monkeypatch.setattr(uploads, "enqueue", queue)

    def database():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"title": "Закупка"}).json()
        yield client, project["id"], queue, sessions
    engine.dispose()


def test_upload_persists_until_explicit_start_and_repeated_start_does_not_duplicate_jobs(workspace):
    client, pid, queue, sessions = workspace
    response = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))])
    assert response.status_code == 202
    uploaded = response.json()["files"][0]
    doc_id = uuid.UUID(uploaded["documents"][0]["id"])
    assert uploaded["phase"] == uploaded["documents"][0]["phase"] == "uploaded"
    assert uploaded["progress"] == 0 and uploaded["traffic_light"] is None
    queue.assert_not_called()

    # Новый HTTP-запрос/сессия БД, как после перезагрузки страницы.
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["files"][0]["phase"] == "uploaded" and saved["processing_count"] == 0

    def verify_committed(ids):
        with sessions() as db:
            assert db.get(Document, ids[0]).status == "QUEUED"
    queue.side_effect = verify_committed
    started = client.post(f"/api/projects/{pid}/start")
    assert started.status_code == 202 and started.json() == {"documents": 1}
    queue.assert_called_once_with([doc_id])
    assert client.get(f"/api/projects/{pid}").json()["processing_count"] == 1
    assert client.post(f"/api/projects/{pid}/start").status_code == 409
    queue.assert_called_once()


def test_start_only_schedules_new_files_in_the_selected_project(workspace):
    client, pid, queue, sessions = workspace
    old = client.post(f"/api/projects/{pid}/files", files=[("files", ("old.txt", b"Old"))]).json()["files"][0]
    with sessions.begin() as db:
        db.get(Analysis, uuid.UUID(old["id"])).analysis_status = "COMPLETED"
        db.get(Document, uuid.UUID(old["documents"][0]["id"])).status = "COMPLETED"
    other = client.post("/api/projects", json={"title": "Другой проект"}).json()["id"]
    client.post(f"/api/projects/{other}/files", files=[("files", ("other.txt", b"Other"))])
    new = client.post(f"/api/projects/{pid}/files", files=[("files", ("new.txt", b"New"))]).json()["files"][0]

    assert client.post(f"/api/projects/{pid}/start").json() == {"documents": 1}
    queue.assert_called_once_with([uuid.UUID(new["documents"][0]["id"])])
    assert client.get(f"/api/projects/{other}").json()["files"][0]["phase"] == "uploaded"
    with sessions() as db:
        assert db.get(Document, uuid.UUID(old["documents"][0]["id"])).status == "COMPLETED"


def test_zip_waits_and_upload_errors_do_not_start_valid_documents(workspace):
    client, pid, queue, _ = workspace
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("contract.txt", "Contract")
        package.writestr("readme.exe", "Unsupported")
    response = client.post(f"/api/projects/{pid}/files", files=[
        ("files", ("bundle.zip", archive.getvalue(), "application/zip")),
        ("files", ("empty.txt", b"")),
    ])
    result = response.json()
    assert response.status_code == 202 and len(result["errors"]) == 1
    assert result["files"][0]["phase"] == "uploaded"
    docs = result["files"][0]["documents"]
    assert {d["phase"] for d in docs} == {"uploaded", "unsupported"}
    queue.assert_not_called()
    assert client.post(f"/api/projects/{pid}/start").json() == {"documents": 1}
    queue.assert_called_once_with([uuid.UUID(next(d["id"] for d in docs if d["phase"] == "uploaded"))])


def test_empty_project_cannot_start_and_queue_failure_can_be_retried(workspace):
    client, pid, queue, sessions = workspace
    assert client.post(f"/api/projects/{pid}/start").status_code == 409
    queue.assert_not_called()
    client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))])
    queue.side_effect = ConnectionError("Unavailable")
    assert client.post(f"/api/projects/{pid}/start").status_code == 503
    failed = client.get(f"/api/projects/{pid}").json()
    assert failed["files"][0]["phase"] == "failed" and failed["processing_count"] == 0
    queue.side_effect = None
    assert client.post(f"/api/projects/{pid}/rerun").json() == {"documents": 1}
    with sessions() as db:
        assert db.scalar(select(Document.status)) == "QUEUED"


def test_start_checks_project_ownership(workspace):
    client, pid, queue, sessions = workspace
    user_id = uuid.uuid4()
    with sessions.begin() as db:
        db.add(User(id=user_id, email="other@example.test", full_name="Other"))
    client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))])
    assert client.post(f"/api/projects/{pid}/start", headers={"X-User-Id": str(user_id)}).status_code == 404
    queue.assert_not_called()


def test_project_rename_persists_without_changing_uploaded_files(workspace):
    client, pid, queue, sessions = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    renamed = client.patch(f"/api/projects/{pid}", json={"title": "  Новый договор  "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Новый договор"
    assert renamed.json()["files"][0]["id"] == uploaded["id"]
    assert client.get(f"/api/projects/{pid}").json()["title"] == "Новый договор"
    assert client.get("/api/projects").json()[0]["title"] == "Новый договор"
    queue.assert_not_called()


def test_project_rename_rejects_blank_long_and_duplicate_titles(workspace):
    client, pid, _, _ = workspace
    client.post("/api/projects", json={"title": "Другой проект"})
    assert client.patch(f"/api/projects/{pid}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"title": "a" * 121}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"title": "Другой проект"}).status_code == 409
    assert client.patch(f"/api/projects/{pid}", json={"title": "ДРУГОЙ ПРОЕКТ"}).status_code == 409
    assert client.get(f"/api/projects/{pid}").json()["title"] == "Закупка"


def test_project_delete_removes_owned_files_and_results_only(workspace):
    client, pid, _, sessions = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    aid, did = uuid.UUID(uploaded["id"]), uuid.UUID(uploaded["documents"][0]["id"])
    other = client.post("/api/projects", json={"title": "Другой"}).json()["id"]
    other_file = client.post(f"/api/projects/{other}/files", files=[("files", ("other.txt", b"Other"))]).json()["files"][0]
    page_id, finding_id = uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as db:
        db.add(DocumentPage(id=page_id, document_id=did, page_number=1, width=595, height=842, text="Contract"))
        db.add(RiskFinding(id=finding_id, analysis_id=aid, document_id=did, title="Risk", severity="HIGH", comment="Review"))
    assert (settings.storage_dir / str(aid)).is_dir()
    deleted = client.delete(f"/api/projects/{pid}")
    assert deleted.status_code == 204 and not deleted.content
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.delete(f"/api/projects/{pid}").status_code == 404
    assert not (settings.storage_dir / str(aid)).exists()
    with sessions() as db:
        for model, identifier in [(Project, uuid.UUID(pid)), (Analysis, aid), (Document, did), (DocumentPage, page_id), (RiskFinding, finding_id)]:
            assert db.get(model, identifier) is None
    assert client.get(f"/api/projects/{other}").json()["files"][0]["id"] == other_file["id"]
    assert (settings.storage_dir / other_file["id"]).is_dir()


def test_project_mutations_check_ownership(workspace):
    client, pid, _, sessions = workspace
    user_id = uuid.uuid4()
    with sessions.begin() as db:
        db.add(User(id=user_id, email="other@example.test", full_name="Other"))
    headers = {"X-User-Id": str(user_id)}
    assert client.patch(f"/api/projects/{pid}", json={"title": "Чужой"}, headers=headers).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=headers).status_code == 404
    assert client.get(f"/api/projects/{pid}").json()["title"] == "Закупка"


def test_delete_waiting_file_removes_storage_and_only_starts_remaining_documents(workspace):
    client, pid, queue, sessions = workspace
    files = client.post(f"/api/projects/{pid}/files", files=[
        ("files", ("remove.txt", b"Remove")), ("files", ("keep.txt", b"Keep")),
    ]).json()["files"]
    removed, kept = files
    aid = uuid.UUID(removed["id"])
    did = uuid.UUID(removed["documents"][0]["id"])
    assert (settings.storage_dir / str(aid)).is_dir()
    response = client.delete(f"/api/projects/{pid}/files/{aid}")
    assert response.status_code == 204 and not response.content
    assert not (settings.storage_dir / str(aid)).exists()
    with sessions() as db:
        assert db.get(Analysis, aid) is None and db.get(Document, did) is None
        assert db.get(Project, uuid.UUID(pid)) is not None
    assert [file["id"] for file in client.get(f"/api/projects/{pid}").json()["files"]] == [kept["id"]]
    assert client.delete(f"/api/projects/{pid}/files/{aid}").status_code == 404
    queue.assert_not_called()
    assert client.post(f"/api/projects/{pid}/start").json() == {"documents": 1}
    queue.assert_called_once_with([uuid.UUID(kept["documents"][0]["id"])])
    assert client.delete(f"/api/projects/{pid}/files/{kept['id']}").status_code == 409
    assert (settings.storage_dir / kept["id"]).is_dir()


def test_delete_last_waiting_file_leaves_empty_project_and_allows_reupload(workspace):
    client, pid, queue, _ = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    assert client.delete(f"/api/projects/{pid}/files/{uploaded['id']}").status_code == 204
    assert client.get(f"/api/projects/{pid}").json()["files"] == []
    assert client.post(f"/api/projects/{pid}/start").status_code == 409
    queue.assert_not_called()
    uploaded_again = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()
    assert len(uploaded_again["files"]) == 1 and not uploaded_again["errors"]


def test_delete_waiting_zip_removes_supported_and_unsupported_children(workspace):
    client, pid, queue, sessions = workspace
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("folder/contract.txt", "Contract")
        package.writestr("readme.exe", "Unsupported")
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("bundle.zip", archive.getvalue(), "application/zip"))]).json()["files"][0]
    assert len(uploaded["documents"]) == 2
    assert client.delete(f"/api/projects/{pid}/files/{uploaded['id']}").status_code == 204
    assert not (settings.storage_dir / uploaded["id"]).exists()
    with sessions() as db:
        for document in uploaded["documents"]:
            assert db.get(Document, uuid.UUID(document["id"])) is None
    queue.assert_not_called()


def test_delete_waiting_file_checks_project_and_user_ownership(workspace):
    client, pid, _, sessions = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    other_project = client.post("/api/projects", json={"title": "Другой"}).json()["id"]
    assert client.delete(f"/api/projects/{other_project}/files/{uploaded['id']}").status_code == 404
    assert client.delete(f"/api/projects/{pid}/files/{uuid.uuid4()}").status_code == 404
    other_user = uuid.uuid4()
    with sessions.begin() as db:
        db.add(User(id=other_user, email="other@example.test", full_name="Other"))
    assert client.delete(f"/api/projects/{pid}/files/{uploaded['id']}", headers={"X-User-Id": str(other_user)}).status_code == 404
    assert client.get(f"/api/projects/{pid}").json()["files"][0]["id"] == uploaded["id"]
    assert (settings.storage_dir / uploaded["id"]).is_dir()


@pytest.mark.parametrize("analysis_status", ["QUEUED", "CONVERTING", "OCR", "VECTORIZING", "ANALYZING", "COMPLETED", "FAILED"])
def test_delete_file_rejects_started_or_finished_analysis(workspace, analysis_status):
    client, pid, _, sessions = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    with sessions.begin() as db:
        db.get(Analysis, uuid.UUID(uploaded["id"])).analysis_status = analysis_status
    response = client.delete(f"/api/projects/{pid}/files/{uploaded['id']}")
    assert response.status_code == 409 and "до начала анализа" in response.json()["detail"]
    with sessions() as db:
        assert db.get(Analysis, uuid.UUID(uploaded["id"])) is not None
        assert db.get(Document, uuid.UUID(uploaded["documents"][0]["id"])) is not None
    assert (settings.storage_dir / uploaded["id"]).is_dir()


def test_delete_file_also_checks_child_document_status(workspace):
    client, pid, _, sessions = workspace
    uploaded = client.post(f"/api/projects/{pid}/files", files=[("files", ("contract.txt", b"Contract"))]).json()["files"][0]
    with sessions.begin() as db:
        db.get(Document, uuid.UUID(uploaded["documents"][0]["id"])).status = "QUEUED"
    assert client.delete(f"/api/projects/{pid}/files/{uploaded['id']}").status_code == 409
    assert (settings.storage_dir / uploaded["id"]).is_dir()
