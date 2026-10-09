"""Загрузка и ручной запуск через HTTP с настоящими транзакциями, без брокера/LLM."""
import io
import uuid
import zipfile
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import projects
from app.config import settings
from app.db import get_db
from app.models import Analysis, Base, Document, User
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
