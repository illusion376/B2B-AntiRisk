import json
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
import httpx
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Analysis, Base, Document, DocumentChatMessage, DocumentPage, RiskFinding, RiskRule, User
from app.services import document_chat
from app.services.llm import LLMClient


@compiles(JSONB, "sqlite")
def _json_sqlite(_type, compiler, **kw):
    return "JSON"


@compiles(Vector, "sqlite")
def _vector_sqlite(_type, compiler, **kw):
    return "TEXT"


@pytest.fixture
def chat(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    state = {"prompts": [], "models": [], "error": None, "reply": None, "locked": False, "during_reply": None}

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("pg_try_advisory_xact_lock", 1, lambda _: int(not state["locked"]))

    Base.metadata.create_all(engine)
    user_id, other_user = uuid.uuid4(), uuid.uuid4()
    doc_id, other_doc, foreign_doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    finding_id, unknown_id, hidden_id, dismissed_id, other_finding = [uuid.uuid4() for _ in range(5)]
    now = datetime(2026, 10, 15, 12)
    with Session(engine) as db:
        db.add_all([User(id=user_id, email="one@example.test", full_name="One"),
                    User(id=other_user, email="two@example.test", full_name="Two")])
        db.flush()
        for document_id, owner in [(doc_id, user_id), (other_doc, user_id), (foreign_doc, other_user)]:
            analysis = Analysis(id=uuid.uuid4(), user_id=owner, title="Поставка", original_filename="contract.pdf",
                                file_type="pdf", analysis_status="COMPLETED", created_at=now)
            db.add(analysis)
            db.flush()
            db.add(Document(id=document_id, analysis_id=analysis.id, file_name="contract.pdf", file_path="not-exposed",
                            status="COMPLETED", total_pages=2, created_at=now, updated_at=now))
            db.flush()
            db.add(DocumentPage(document_id=document_id, page_number=1, width=600, height=800,
                                text="6.2. Поставщик уплачивает штраф 10 процентов. "
                                     + ("ЧУЖОЙ_ДОКУМЕНТ" if document_id != doc_id else "НАШ_ДОКУМЕНТ")))
            if document_id == doc_id:
                db.add(RiskRule(id="hidden", title="Отключённое", description="", semantic_query="", llm_prompt="",
                                category="Оплата", severity="RED", is_active=False))
                db.flush()
                for idx, fid, level, rule, review in [
                    (0, finding_id, "RED", None, "NEW"), (1, unknown_id, "UNKNOWN", None, "NEW"),
                    (2, hidden_id, "RED", "hidden", "NEW"), (3, dismissed_id, "YELLOW", None, "DISMISSED"),
                ]:
                    db.add(RiskFinding(id=fid, analysis_id=analysis.id, document_id=document_id, rule_id=rule,
                                       title="Скрытое" if rule else "Штраф", severity=level, comment="Размер штрафа требует проверки",
                                       page_number=1, clause="6.2", exact_quote="штраф 10 процентов", quote_verified=True,
                                       source="LLM", sort_index=idx, review_status=review))
            elif document_id == other_doc:
                db.add(RiskFinding(id=other_finding, analysis_id=analysis.id, document_id=document_id,
                                   title="Чужое замечание", severity="RED", comment="", sort_index=0))
        db.commit()

    def session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    class FakeLLM:
        def __init__(self, **kwargs):
            assert kwargs["response_schema"]["additionalProperties"] is False
            state["models"].append(kwargs["model"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def complete_json(self, system, user):
            prompt = json.loads(user)
            state["prompts"].append(prompt)
            if state["during_reply"]:
                state["during_reply"]()
            if state["error"]:
                raise state["error"]
            if state["reply"]:
                return state["reply"]
            draft = prompt["mode"] != "question" or bool(prompt["latest_draft"])
            return {"answer": "Проверьте размер штрафа в пункте 6.2.",
                    "source_ids": [prompt["server_context"]["sources"][0]["id"]],
                    "draft_title": "Протокол разногласий" if draft else None,
                    "draft_content": "Пункт 6.2\nПредложение: согласовать соразмерный штраф." if draft else None}

    monkeypatch.setattr(settings, "default_user_id", str(user_id))
    monkeypatch.setattr(settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(document_chat, "LLMClient", FakeLLM)
    app.dependency_overrides[get_db] = session
    client = TestClient(app)
    yield SimpleNamespace(client=client, engine=engine, state=state, document_id=doc_id, user_id=user_id,
                          other_user=other_user, other_doc=other_doc, foreign_doc=foreign_doc, finding_id=finding_id,
                          hidden_id=hidden_id, dismissed_id=dismissed_id, other_finding=other_finding,
                          url=f"/api/documents/{doc_id}/chat")
    client.close()
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.mark.parametrize("model", ["openai/gpt-6-luna", "anthropic/claude-haiku-5-5",
                                   "deepseek/deepseek-v4-flash", None])
def test_assistant_sends_saved_analysis_model_to_provider(chat, monkeypatch, model):
    with Session(chat.engine) as db:
        document = db.get(Document, chat.document_id)
        document.analysis_mode = "llm" if model else "keyword"
        document.llm_model = model
        db.commit()
    monkeypatch.setattr(settings, "llm_model", "server-default-model")
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        reply = {"answer": "Ответ по документу", "source_ids": [], "draft_title": None, "draft_content": None}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(provider)))
    monkeypatch.setattr(document_chat, "LLMClient", LLMClient)
    response = chat.client.post(chat.url, json={"message": "Объясни результат проверки"})
    assert response.status_code == 200, response.text
    assert [request["model"] for request in requests] == [model or "server-default-model"]


def test_assistant_model_is_scoped_to_each_document(chat):
    models = ["deepseek/deepseek-v4-flash", "anthropic/claude-haiku-5-5"]
    with Session(chat.engine) as db:
        for document_id, model in zip([chat.document_id, chat.other_doc], models):
            db.get(Document, document_id).llm_model = model
        db.commit()
    for document_id in [chat.document_id, chat.other_doc, chat.document_id]:
        response = chat.client.post(f"/api/documents/{document_id}/chat", json={"message": "Вопрос"})
        assert response.status_code == 200, response.text
    assert chat.state["models"] == [*models, models[0]]


def test_turn_uses_server_document_findings_and_preserves_history(chat):
    result = chat.client.post(chat.url, json={"message": "Почему это риск?", "finding_id": str(chat.finding_id)})
    assert result.status_code == 200, result.text
    messages = result.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["sources"][0]["finding_id"] == str(chat.finding_id)
    context = chat.state["prompts"][0]["server_context"]
    assert context["selected_finding"] == str(chat.finding_id)
    assert context["report"]["risk_score"] is None
    assert context["report"]["assessed"] is False
    assert context["report"]["counts"]["UNKNOWN"] == 1
    assert len(context["findings"]) == 2
    assert "НАШ_ДОКУМЕНТ" in json.dumps(context, ensure_ascii=False)
    assert "ЧУЖОЙ_ДОКУМЕНТ" not in json.dumps(context, ensure_ascii=False)
    assert "not-exposed" not in json.dumps(context)
    saved = chat.client.get(chat.url).json()["messages"]

    assert [{k: v for k, v in m.items() if k != "created_at"} for m in saved] == [
        {k: v for k, v in m.items() if k != "created_at"} for m in messages]
    assert chat.client.post(chat.url, json={"message": "Как его исправить?"}).status_code == 200
    assert len(chat.state["prompts"][1]["history"]) == 2


@pytest.mark.parametrize("target", ["other_finding", "hidden_id"])
def test_foreign_or_disabled_finding_is_rejected_without_calling_llm(chat, target):
    response = chat.client.post(chat.url, json={"message": "Объясни", "finding_id": str(getattr(chat, target))})
    assert response.status_code == 404
    assert chat.state["prompts"] == []


def test_explicit_dismissed_finding_can_be_discussed_without_changing_report(chat):
    result = chat.client.post(chat.url, json={"message": "Почему отклонено?", "finding_id": str(chat.dismissed_id)})
    assert result.status_code == 200
    context = chat.state["prompts"][0]["server_context"]
    assert context["findings"][0]["status"] == "dismissed"
    assert context["report"]["counts"]["YELLOW"] == 0


def test_ownership_and_document_isolation(chat):
    for method in ("get", "post"):
        kwargs = {"json": {"message": "Вопрос"}} if method == "post" else {}
        assert getattr(chat.client, method)(chat.url, headers={"X-User-Id": str(chat.other_user)}, **kwargs).status_code == 404
        assert getattr(chat.client, method)(f"/api/documents/{chat.foreign_doc}/chat", **kwargs).status_code == 404
    assert chat.client.get(f"/api/documents/{chat.other_doc}/chat").json()["messages"] == []
    assert not chat.state["prompts"]


@pytest.mark.parametrize("payload", [{"message": " "}, {"message": "a" * 4001}, {"message": "Вопрос", "history": []},
                                     {"message": "Вопрос", "context": "fake"}, {"message": "Вопрос", "mode": "edit-file"},
                                     {"message": "Вопрос", "model": "client-model"},
                                     {"message": "Вопрос", "llm_model": "client-model"}])
def test_client_cannot_supply_context_or_unbounded_requests(chat, payload):
    assert chat.client.post(chat.url, json=payload).status_code == 422
    assert not chat.state["prompts"]


def test_unconfigured_provider_is_explicit_and_history_remains_readable(chat, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
    assert chat.client.get(chat.url).json()["available"] is False
    assert chat.client.post(chat.url, json={"message": "Вопрос"}).status_code == 503
    assert not chat.state["prompts"]


def test_provider_failure_does_not_save_half_a_turn_or_expose_secrets(chat):
    with Session(chat.engine) as db:
        db.get(Document, chat.document_id).llm_model = "deepseek/deepseek-v4-flash"
        db.commit()
    chat.state["error"] = RuntimeError("SECRET and sensitive contract")
    result = chat.client.post(chat.url, json={"message": "Вопрос"})
    assert result.status_code == 502
    assert "SECRET" not in result.text
    assert chat.client.get(chat.url).json()["messages"] == []
    assert chat.state["models"] == ["deepseek/deepseek-v4-flash"]


@pytest.mark.parametrize("reply", [
    {"answer": " ", "source_ids": [], "draft_title": None, "draft_content": None},
    {"answer": "Ответ", "source_ids": ["invented-page-999"], "draft_title": None, "draft_content": None},
    {"answer": "Ответ", "source_ids": [], "draft_title": "Report", "draft_content": None},
    {"answer": "Ответ", "source_ids": [], "draft_title": "Report", "draft_content": "bad\x00text"},
])
def test_invalid_model_output_cannot_be_saved_as_an_answer(chat, reply):
    chat.state["reply"] = reply
    assert chat.client.post(chat.url, json={"message": "Вопрос"}).status_code == 502
    assert chat.client.get(chat.url).json()["messages"] == []


def test_concurrent_turn_is_rejected_before_provider_call(chat):
    chat.state["locked"] = True
    assert chat.client.post(chat.url, json={"message": "Вопрос"}).status_code == 409
    assert not chat.state["prompts"]


def test_new_analysis_does_not_reuse_old_conversation(chat):
    with Session(chat.engine) as db:
        db.get(Document, chat.document_id).llm_model = "deepseek/deepseek-v4-flash"
        db.commit()
    chat.client.post(chat.url, json={"message": "Старый вопрос"})
    with Session(chat.engine) as db:
        document = db.get(Document, chat.document_id)
        document.chat_revision = uuid.uuid4()
        document.llm_model = "anthropic/claude-haiku-5-5"
        db.commit()
    assert chat.client.get(chat.url).json()["messages"] == []
    assert chat.client.post(chat.url, json={"message": "Новый вопрос"}).status_code == 200
    assert chat.state["prompts"][-1]["history"] == []
    assert chat.state["models"] == ["deepseek/deepseek-v4-flash", "anthropic/claude-haiku-5-5"]


def test_rename_and_review_keep_the_conversation(chat):
    chat.client.post(chat.url, json={"message": "Вопрос"})
    with Session(chat.engine) as db:
        document = db.get(Document, chat.document_id)
        document.file_name = "new-name.pdf"
        document.updated_at += timedelta(seconds=1)
        db.get(RiskFinding, chat.finding_id).review_status = "CONFIRMED"
        db.commit()
    assert len(chat.client.get(chat.url).json()["messages"]) == 2
    assert chat.client.post(chat.url, json={"message": "Продолжи"}).status_code == 200
    context = chat.state["prompts"][-1]["server_context"]
    assert context["document"]["name"] == "new-name.pdf"
    assert context["findings"][0]["status"] == "accepted"


def test_changed_findings_during_generation_reject_stale_answer(chat):
    def update():
        with Session(chat.engine) as db:
            db.get(RiskFinding, chat.finding_id).review_status = "DISMISSED"
            db.commit()
    chat.state["during_reply"] = update
    assert chat.client.post(chat.url, json={"message": "Вопрос"}).status_code == 409
    assert chat.client.get(chat.url).json()["messages"] == []


def test_unfinished_document_cannot_start_chat(chat):
    with Session(chat.engine) as db:
        db.get(Document, chat.document_id).status = "ANALYZING"
        db.commit()
    assert chat.client.get(chat.url).status_code == 409
    assert chat.client.post(chat.url, json={"message": "Вопрос"}).status_code == 409


def test_draft_can_be_refined_and_downloaded_only_by_its_owner(chat):
    response = chat.client.post(chat.url, json={"message": "Составь протокол", "mode": "protocol"})
    assert response.status_code == 200, response.text
    message = response.json()["messages"][1]
    response = chat.client.get(f"{chat.url}/{message['id']}/draft")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    word = WordDocument(BytesIO(response.content))
    content = "\n".join(p.text for p in word.paragraphs)
    assert "Протокол разногласий" in content
    assert "Пункт 6.2" in content
    assert "Источники" in content
    assert word.core_properties.author == "One"
    profile = chat.client.patch("/api/users/me", json={"full_name": "Анна Петрова", "company_name": "ООО «Поставщик»"})
    assert profile.status_code == 200
    updated = WordDocument(BytesIO(chat.client.get(f"{chat.url}/{message['id']}/draft").content))
    updated_text = "\n".join(p.text for p in updated.paragraphs)
    assert "Подготовил: Анна Петрова" in updated_text
    assert "Компания: ООО «Поставщик»" in updated_text
    assert updated.core_properties.author == "Анна Петрова"
    assert chat.client.get(f"{chat.url}/{message['id']}/draft", headers={"X-User-Id": str(chat.other_user)}).status_code == 404
    assert chat.client.get(f"/api/documents/{chat.other_doc}/chat/{message['id']}/draft").status_code == 404
    assert chat.client.post(chat.url, json={"message": "Сократи черновик"}).status_code == 200
    assert chat.state["prompts"][-1]["latest_draft"]["content"] == message["draft_content"]
    with Session(chat.engine) as db:
        assert db.get(RiskFinding, chat.finding_id).review_status == "NEW"
        assert len(list(db.scalars(select(DocumentChatMessage)))) == 4


def test_short_document_is_complete_and_long_document_retrieves_distant_passage():
    passages, truncated = document_chat.select_passages([(1, "Первый"), (2, "Последний")], "", None)
    assert [p["page"] for p in passages] == [1, 2]
    assert not truncated
    pages = [(p, "Обычный текст. " * 400) for p in range(1, 101)]
    pages.append((101, "Особые условия поставки. Срок поставки 3 дня."))
    passages, truncated = document_chat.select_passages(pages, "Какой срок поставки?", None, budget=8000)
    assert truncated
    assert any(p["page"] == 101 for p in passages)
    assert sum(len(p["text"]) for p in passages) <= 8000
    passages, _ = document_chat.select_passages(pages, "Объясни на странице 99", 100, budget=12000)
    assert {99, 100}.issubset({p["page"] for p in passages})


@pytest.mark.parametrize("mode", ["question", "report", "protocol"])
def test_off_topic_refusal_is_saved_without_sources_or_draft(chat, mode):
    chat.state["reply"] = {
        "answer": document_chat.OFF_TOPIC_ANSWER, "source_ids": [],
        "draft_title": None, "draft_content": None,
    }
    response = chat.client.post(chat.url, json={
        "message": "Реши мне уравнение 2x - 50 = 3x - 67",
        "finding_id": str(chat.finding_id), "mode": mode,
    })
    assert response.status_code == 200
    reply = response.json()["messages"][1]
    assert reply["content"] == document_chat.OFF_TOPIC_ANSWER
    assert reply["sources"] == []
    assert reply["draft_title"] is None
    assert reply["draft_content"] is None
    assert len(chat.client.get(chat.url).json()["messages"]) == 2
    chat.state["reply"] = None
    assert chat.client.post(chat.url, json={"message": "Как исправить штраф в пункте 6.2?"}).status_code == 200
