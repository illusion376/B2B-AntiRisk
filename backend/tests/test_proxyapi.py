import asyncio
import json

import httpx
import pytest
from tenacity import wait_none

from app.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def proxy_config(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "https://api.proxyapi.ru/v1/")
    monkeypatch.setattr(settings, "llm_model", "openai/gpt-4.1-mini")
    monkeypatch.setattr(settings, "llm_api_key", "test-proxy-key")
    monkeypatch.setattr(settings, "llm_json_mode", True)
    monkeypatch.setattr(llm, "wait_exponential", lambda **kwargs: wait_none())


def complete(monkeypatch, handler, *, response_schema=None):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler)))

    async def run():
        async with llm.LLMClient(response_schema=response_schema) as client:
            return await client.complete_json("Ответь JSON-объектом", "Проверить документ")
    return asyncio.run(run())


def answer():
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop", "message": {"content": '{"verdict":"UNKNOWN"}'},
    }]})


def test_proxyapi_endpoint_auth_model_and_response(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.proxyapi.ru/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-proxy-key"
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-4.1-mini"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][1]["content"] == "Проверить документ"
        return answer()

    assert complete(monkeypatch, handler) == {"verdict": "UNKNOWN"}
    assert len(calls) == 1


@pytest.mark.parametrize("base_url", [
    "https://api.proxyapi.ru/v1",
    " https://api.proxyapi.ru/v1/ ",
])
@pytest.mark.parametrize("model", ["openai/gpt-5-mini", " gpt-5-mini "])
def test_proxyapi_reasoning_model_and_strict_schema_work_together(monkeypatch, base_url, model):
    from app.services.analyzer import LLMResult

    monkeypatch.setattr(settings, "llm_base_url", base_url)
    monkeypatch.setattr(settings, "llm_api_key", " test-proxy-key ")
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "llm_max_tokens", 8192)
    monkeypatch.setattr(settings, "llm_reasoning_effort", "low")
    schema = LLMResult.model_json_schema()
    result = {"verdict": "NOT_FOUND", "issues": [], "evidence": [], "explanation": "Условие не найдено."}
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.proxyapi.ru/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-proxy-key"
        payload = json.loads(request.content)
        assert payload["model"] == model.strip()
        assert payload["max_completion_tokens"] == 8192
        assert payload["reasoning_effort"] == "low"
        assert "max_tokens" not in payload and "temperature" not in payload
        assert payload["response_format"] == {"type": "json_schema", "json_schema": {
            "name": "risk_rule_result", "strict": True, "schema": schema,
        }}
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(result)},
        }]})

    assert complete(monkeypatch, handler, response_schema=schema) == result
    assert len(calls) == 1


def test_proxyapi_rate_limit_is_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429) if len(calls) == 1 else answer()

    assert complete(monkeypatch, handler) == {"verdict": "UNKNOWN"}
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 402])
def test_proxyapi_key_and_balance_errors_do_not_retry_or_log_secrets(monkeypatch, caplog, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="test-proxy-key sensitive-contract-text")

    with pytest.raises(httpx.HTTPStatusError):
        complete(monkeypatch, handler)
    assert len(calls) == 1
    assert "test-proxy-key" not in caplog.text
    assert "sensitive-contract-text" not in caplog.text


def test_provider_without_json_mode_keeps_the_same_model(monkeypatch):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(400, text="unsupported response_format") if len(payloads) == 1 else answer()

    assert complete(monkeypatch, handler) == {"verdict": "UNKNOWN"}
    assert len(payloads) == 2
    assert "response_format" not in payloads[1]
    assert payloads[0]["model"] == payloads[1]["model"]


def test_no_key_fails_without_sending_a_request(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(llm.LLMError, match="LLM_API_KEY"):
        llm.LLMClient()
