"""Сохранение профиля и экспорт отчётов через HTTP с настоящими транзакциями."""
import csv
import io
import uuid

import pymupdf
import pytest
from docx import Document as DocxDocument
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import reports, system
from app.config import settings
from app.db import get_db
from app.models import Analysis, Base, Document, User


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def sqlite_uuid(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def profile_workspace(tmp_path, contract_pdf, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'profile.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    owner = uuid.UUID(settings.default_user_id)
    other = uuid.uuid4()
    aid, did = uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as db:
        db.add_all([
            User(id=owner, email="analyst@example.test", full_name="Аналитик", company_name="Старая компания"),
            User(id=other, email="other@example.test", full_name="Другой пользователь", company_name="Другая компания"),
            Analysis(id=aid, user_id=owner, title="Контракт", original_filename="Контракт.pdf", file_type="pdf", analysis_status="COMPLETED"),
            Document(id=did, analysis_id=aid, file_name="Контракт.pdf", status="COMPLETED", total_pages=2,
                     is_scanned=False, file_path=str(contract_pdf), preview_path=str(contract_pdf)),
        ])
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "files")

    def database():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(system.router)
    app.include_router(reports.router)
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, owner, other, aid, did, sessions
    engine.dispose()


def test_profile_is_committed_and_updates_only_the_current_user(profile_workspace):
    client, owner, other, _, _, sessions = profile_workspace
    response = client.patch("/api/users/me", json={"full_name": "  Иван Иванов  ", "company_name": " ООО «Поставщик» "})
    assert response.status_code == 200
    profile = response.json()
    assert profile["full_name"] == "Иван Иванов" and profile["company_name"] == "ООО «Поставщик»"
    assert profile["initials"] == "ИИ" and profile["id"] == str(owner)
    assert client.get("/api/users/me").json() == profile
    with sessions() as db:
        assert db.get(User, owner).full_name == "Иван Иванов"
        assert db.get(User, other).full_name == "Другой пользователь"
    client.patch("/api/users/me", headers={"X-User-Id": str(other)},
                 json={"full_name": "Анна Петрова", "company_name": "ООО «Другой»"})
    assert client.get("/api/users/me").json() == profile
    assert client.get("/api/users/me", headers={"X-User-Id": str(other)}).json()["initials"] == "АП"


@pytest.mark.parametrize("company", [None, "", "   "])
def test_company_can_be_cleared_without_losing_the_name(profile_workspace, company):
    client, *_ = profile_workspace
    response = client.patch("/api/users/me", json={"full_name": "Аналитик", "company_name": company})
    assert response.status_code == 200 and response.json()["company_name"] is None
    assert client.get("/api/users/me").json()["full_name"] == "Аналитик"


def test_omitting_company_preserves_it(profile_workspace):
    client, *_ = profile_workspace
    response = client.patch("/api/users/me", json={"full_name": "Новое имя"})
    assert response.status_code == 200
    assert response.json()["company_name"] == "Старая компания"


@pytest.mark.parametrize("payload", [
    {"full_name": "   "}, {"full_name": ""}, {"full_name": None}, {"full_name": "a" * 256},
    {"full_name": "Имя", "company_name": "a" * 256}, {"full_name": "Имя", "role": "ADMIN"},
    {"full_name": "Имя", "email": "replacement@example.test"},
])
def test_invalid_profiles_cannot_change_saved_data(profile_workspace, payload):
    client, *_ = profile_workspace
    before = client.get("/api/users/me").json()
    assert client.patch("/api/users/me", json=payload).status_code == 422
    assert client.get("/api/users/me").json() == before


@pytest.mark.parametrize(("endpoint", "mode", "fmt"), [
    ("documents", "detailed", "docx"), ("analyses", "brief", "docx"), ("documents", "protocol", "docx"),
    ("analyses", "detailed", "json"), ("documents", "brief", "csv"), ("documents", "annotated", "pdf"),
    ("documents", "brief", "pdf"),
])
def test_saved_profile_is_used_by_new_reports(profile_workspace, endpoint, mode, fmt):
    client, _, _, aid, did, _ = profile_workspace
    name, company = "Анна Петрова", "ООО «Поставщик»"
    assert client.patch("/api/users/me", json={"full_name": name, "company_name": company}).status_code == 200
    report_id = did if endpoint == "documents" else aid
    response = client.get(f"/api/{endpoint}/{report_id}/report", params={"mode": mode, "format": fmt})
    assert response.status_code == 200, response.text
    if fmt == "docx":
        document = DocxDocument(io.BytesIO(response.content))
        text = "\n".join(p.text for p in document.paragraphs) + "\n".join(
            cell.text for table in document.tables for row in table.rows for cell in row.cells)
        assert name in text and company in text
        assert document.core_properties.author == name
    elif fmt == "json":
        assert response.json()["author"] == name and response.json()["company"] == company
    elif fmt == "csv":
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        assert ["Подготовил", name] in rows and ["Компания", company] in rows
    else:
        with pymupdf.open(stream=response.content, filetype="pdf") as document:
            if mode == "annotated":
                assert document.metadata["author"] == name
                notes = "\n".join(a.info["content"] for page in document for a in (page.annots() or []))
                assert name in notes and company in notes
                assert document.page_count == 2
            else:
                text = "\n".join(page.get_text() for page in document)
                assert name in text and company in text


def test_company_formula_is_escaped_in_csv_report(profile_workspace):
    client, _, _, _, did, _ = profile_workspace
    assert client.patch("/api/users/me", json={"full_name": "Аналитик", "company_name": '=HYPERLINK("https://example.test")'}).status_code == 200
    response = client.get(f"/api/documents/{did}/report", params={"mode": "brief", "format": "csv"})
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert ["Компания", '\'=HYPERLINK("https://example.test")'] in rows
