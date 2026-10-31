"""Model selection reaches the queue and HTTP payload without mutating global settings."""
import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import analyses, documents, projects
from app.config import Settings
from app.main import app
from app.models import Analysis, Document, Project, User
from app.services import analysis_models, analysis_modes, llm, pipeline


@pytest.fixture
def model_settings(monkeypatch):
    config = Settings(_env_file=None, llm_base_url="https://api.proxyapi.ru/v1",
                      llm_api_key="private-catalog-key", llm_model="openai/gpt-4.1-mini")
    for module in (analysis_models, analysis_modes, llm, pipeline):
        monkeypatch.setattr(module, "settings", config)
    analysis_models._cache.clear()
    return config


def mock_catalog(monkeypatch, payload, status=200):
    requests = []
    original = httpx.Client

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(analysis_models.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handle)))
    return requests


def test_catalog_only_exposes_three_requested_models_and_caches_availability(monkeypatch, model_settings):
    requests = mock_catalog(monkeypatch, {"data": [{"id": value} for value in [
        "openai/gpt-4.1-mini", "anthropic/claude-sonnet-4-5", "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-flash", "deepseek/deepseek-chat", "qwen/qwen-plus", "openai/gpt-5-mini", "google/gemini-3.5-flash", "openai/text-embedding-3-small",
        "openai/gpt-image-1", "openai/gpt-4o-audio-preview", "google/gemini-3-pro-image",
        "google/gemini-nano-banana-2.1", "qwen/qwen3-tts", "deepseek/deepseek-ocr",
    ]]})
    body = TestClient(app).get("/api/analysis-models")
    assert body.status_code == 200
    assert [item["id"] for item in body.json()["models"]] == [
        "openai/gpt-4.1-mini", "anthropic/claude-sonnet-4-5", "deepseek/deepseek-v4-flash",
    ]
    assert all(item["available"] for item in body.json()["models"])
    assert body.json()["source"] == "provider"
    assert body.json()["models"][0]["recommended"]
    analysis_models.model_catalog()
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.proxyapi.ru/v1/models"
    assert requests[0].headers["Authorization"] == "Bearer private-catalog-key"
    assert "private-catalog-key" not in body.text and "https://api.proxyapi.ru" not in body.text


@pytest.mark.parametrize("payload,status", [({"detail": "private-provider-error"}, 403), ({}, 200), ({"data": None}, 200)])
def test_catalog_failure_keeps_exactly_three_choices_and_an_allowed_default(monkeypatch, model_settings, payload, status):
    model_settings.llm_model = "custom/text-model"
    mock_catalog(monkeypatch, payload, status)
    catalog = analysis_models.model_catalog()
    assert catalog.source == "fallback" and catalog.warning
    assert "private-provider-error" not in catalog.model_dump_json()
    assert {"openai/gpt-4.1-mini", "anthropic/claude-sonnet-4-5", "deepseek/deepseek-v4-flash"} == {
        model.id for model in catalog.models if model.available}
    assert catalog.default_model == "openai/gpt-4.1-mini"
    assert analysis_models.analysis_model_or_422(None, "llm") == catalog.default_model


def test_missing_key_never_calls_provider_and_does_not_enable_models(monkeypatch, model_settings):
    model_settings.llm_api_key = None
    requests = mock_catalog(monkeypatch, {"data": []})
    assert not any(model.available for model in analysis_models.model_catalog().models)
    assert analysis_models.analysis_model_or_422("qwen/qwen-plus", "keyword") is None
    assert not requests


def test_removed_default_requires_a_new_choice(monkeypatch, model_settings):
    mock_catalog(monkeypatch, {"data": [{"id": "deepseek/deepseek-v4-flash"}]})
    catalog = analysis_models.model_catalog()
    assert not next(model for model in catalog.models if model.id == model_settings.llm_model).available
    with pytest.raises(HTTPException) as error:
        analysis_models.analysis_model_or_422(model_settings.llm_model, "llm")
    assert error.value.detail["code"] == "analysis_model_unavailable"


@pytest.mark.parametrize("model", ["https://evil.example/model", "unknown/missing", "../qwen/qwen-plus", " ",
                                     "qwen/qwen-plus", "deepseek/deepseek-chat", "openai/gpt-5-mini", "google/gemini-3.5-flash"])
def test_unknown_models_fail_before_queueing(monkeypatch, model_settings, model):
    mock_catalog(monkeypatch, {"data": [{"id": "deepseek/deepseek-v4-flash"}]})
    with pytest.raises(HTTPException) as error:
        analysis_models.analysis_model_or_422(model, "llm")
    assert error.value.status_code == 422


@pytest.mark.parametrize("endpoint,initial", [("start", "UPLOADED"), ("rerun", "COMPLETED"),
                                               ("document", "COMPLETED"), ("analysis", "COMPLETED")])
def test_every_launch_persists_model_before_enqueueing(monkeypatch, model_settings, endpoint, initial):
    mock_catalog(monkeypatch, {"data": [{"id": "anthropic/claude-sonnet-4-5"}, {"id": model_settings.llm_model}]})
    db = MagicMock()
    user = User(id=uuid.uuid4())
    analysis = Analysis(id=uuid.uuid4(), original_filename="contract.txt", analysis_status=initial)
    project = Project(id=uuid.uuid4(), title="Model selection")
    project.analyses = [analysis]
    doc = Document(id=uuid.uuid4(), analysis_id=analysis.id, status=initial, file_name="contract.txt")
    db.scalars.side_effect = [[analysis], [doc]] if endpoint == "start" else [[doc]]
    db.get.return_value = analysis
    monkeypatch.setattr(projects, "get_project_or_404", lambda *_: project)
    monkeypatch.setattr(documents, "get_document_or_404", lambda *_: doc)
    monkeypatch.setattr(analyses, "get_analysis_or_404", lambda *_: analysis)
    monkeypatch.setattr(documents, "document_out", lambda *_: None)
    monkeypatch.setattr(analyses, "analysis_detail", lambda *_: None)
    for module in (documents, analyses):
        monkeypatch.setattr(module, "refresh_analysis", MagicMock())
    queued = []

    def enqueue(_db, docs, *_args):
        assert db.commit.called
        queued.extend((item.analysis_mode, item.llm_model) for item in docs)

    for module in (projects, documents, analyses):
        monkeypatch.setattr(module, "enqueue_documents", enqueue)
    from app.schemas import StartRequest, RerunRequest
    body = RerunRequest(analysis_mode="llm", llm_model="anthropic/claude-sonnet-4-5")
    if endpoint == "start":
        projects.start_project(project.id, db=db, user=user, body=StartRequest(**body.model_dump(exclude={"rule_ids"})))
    elif endpoint == "rerun":
        projects.rerun_project(project.id, db=db, user=user, body=body)
    elif endpoint == "document":
        documents.reanalyze(doc.id, db=db, user=user, body=body)
    else:
        analyses.rerun_analysis(analysis.id, body=body, db=db, user=user)
    assert queued == [("llm", "anthropic/claude-sonnet-4-5")]
    assert model_settings.llm_model == "openai/gpt-4.1-mini"


@pytest.mark.parametrize("saved", ["deepseek/deepseek-v4-flash", "qwen/qwen-plus"])
def test_worker_uses_saved_model_even_after_default_changes(monkeypatch, model_settings, saved):
    doc = Document(id=uuid.uuid4(), analysis_id=uuid.uuid4(), file_name="contract.txt", analysis_mode="llm",
                   analysis_sensitivity="balanced", llm_model=saved)
    model_settings.llm_model = "anthropic/claude-sonnet-4-5"
    db = MagicMock()
    db.get.return_value = doc

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(pipeline, "session_scope", session)
    monkeypatch.setattr(pipeline, "applicable_rules", lambda *_: [])
    for name in ("ensure_rule_embeddings", "_save_findings", "_renumber", "refresh_analysis"):
        monkeypatch.setattr(pipeline, name, MagicMock())
    evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr(pipeline, "evaluate_with_llm", evaluate)
    pipeline.analyze_document(doc.id)
    assert evaluate.call_args.kwargs["model"] == saved


def test_parallel_llm_clients_keep_their_own_model_and_parameters(monkeypatch, model_settings):
    import json
    payloads = []

    async def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))

    async def run():
        async with llm.LLMClient(model="deepseek/deepseek-v4-flash") as first, llm.LLMClient(model="openai/gpt-5-mini") as second:
            model_settings.llm_model = "changed-global-model"
            await asyncio.gather(first.complete_json("JSON", "first"), second.complete_json("JSON", "second"))

    asyncio.run(run())
    assert payloads[0]["model"] == "deepseek/deepseek-v4-flash" and "max_tokens" in payloads[0]
    assert payloads[1]["model"] == "openai/gpt-5-mini" and "max_completion_tokens" in payloads[1]


def test_empty_provider_catalog_disables_all_three_choices(monkeypatch, model_settings):
    mock_catalog(monkeypatch, {"data": []})
    catalog = analysis_models.model_catalog()
    assert catalog.source == "provider"
    assert len(catalog.models) == 3
    assert not any(model.available for model in catalog.models)
