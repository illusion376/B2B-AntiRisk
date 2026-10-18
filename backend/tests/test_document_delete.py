import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import documents
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
def delete_workspace(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'delete.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    owner = uuid.UUID(settings.default_user_id)
    other = uuid.uuid4()
    aid = uuid.uuid4()
    did1 = uuid.uuid4()
    did2 = uuid.uuid4()
    foreign_aid = uuid.uuid4()
    foreign_did = uuid.uuid4()

    with sessions.begin() as db:
        db.add_all([
            User(id=owner, email="owner@test.ru", full_name="Владелец", company_name="Компания"),
            User(id=other, email="other@test.ru", full_name="Другой", company_name="Компания 2"),
            Analysis(id=aid, user_id=owner, title="Archive", original_filename="archive.zip", file_type="zip", analysis_status="COMPLETED"),
            Document(id=did1, analysis_id=aid, file_name="doc1.pdf", status="COMPLETED", total_pages=1, is_scanned=False, file_path="doc1.pdf"),
            Document(id=did2, analysis_id=aid, file_name="doc2.pdf", status="COMPLETED", total_pages=1, is_scanned=False, file_path="doc2.pdf"),
            Analysis(id=foreign_aid, user_id=other, title="Foreign", original_filename="f.pdf", file_type="pdf", analysis_status="COMPLETED"),
            Document(id=foreign_did, analysis_id=foreign_aid, file_name="f.pdf", status="COMPLETED", total_pages=1, is_scanned=False, file_path="f.pdf"),
        ])

    def database():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(documents.router)
    app.dependency_overrides[get_db] = database
    return TestClient(app), sessions, did1, did2, foreign_did


def test_delete_document_success(delete_workspace):
    client, sessions, did1, did2, _ = delete_workspace
    response = client.delete(f"/api/documents/{did1}")
    assert response.status_code == 204

    with sessions() as db:
        assert db.query(Document).filter(Document.id == did1).first() is None
        assert db.query(Document).filter(Document.id == did2).first() is not None


def test_delete_document_not_found(delete_workspace):
    client, _, _, _, _ = delete_workspace
    random_id = uuid.uuid4()
    response = client.delete(f"/api/documents/{random_id}")
    assert response.status_code == 404


def test_delete_document_foreign_user_forbidden(delete_workspace):
    client, _, _, _, foreign_did = delete_workspace
    response = client.delete(f"/api/documents/{foreign_did}")
    assert response.status_code == 404
