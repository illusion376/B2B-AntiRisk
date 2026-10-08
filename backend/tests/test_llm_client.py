import asyncio
import json

import httpx
import pytest

from app.services import llm
from app.services.llm import LLMClient, LLMError, parse_json_response


@pytest.mark.parametrize("content", [
    "", None, [], "[]", "{not json}", '{"verdict":"RISK","verdict":"OK"}',
    '{"confidence": NaN}', '{"confidence": Infinity}', '{"confidence": -Infinity}',
])
def test_json_parser_rejects_ambiguous_or_non_json_results(content):
    with pytest.raises(LLMError):
        parse_json_response(content)


@pytest.mark.parametrize("provider_payload", [
    {}, {"choices": []}, {"choices": None}, {"choices": [None]},
    {"choices": [{"message": {"content": ["text"]}}]},
    {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": "{}", "refusal": "Cannot comply"}}]},
    {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]},
    {"choices": [{"message": {"content": "{}"}, "finish_reason": "content_filter"}]},
])
def test_invalid_provider_envelopes_are_explicit_errors(monkeypatch, provider_payload):
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1",
                                               transport=httpx.MockTransport(lambda request: httpx.Response(200, json=provider_payload)))
            with pytest.raises(LLMError):
                await client._chat("system", "prompt")
    asyncio.run(run())


def test_provider_request_uses_configured_path_model_and_json_mode(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_model", "configured-model")
    monkeypatch.setattr(llm.settings, "llm_json_mode", True)
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "configured-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"] == [{"role": "system", "content": "system"}, {"role": "user", "content": "prompt"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"verdict":"NOT_FOUND"}'}, "finish_reason": "stop"}]})
    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            assert await client.complete_json("system", "prompt") == {"verdict": "NOT_FOUND"}
    asyncio.run(run())


def test_missing_llm_endpoint_fails_explicitly(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_base_url", "")
    with pytest.raises(LLMError, match="LLM_BASE_URL"):
        LLMClient()


def test_exhausted_provider_retries_log_safe_http_code(monkeypatch, caplog):
    from tenacity import wait_none
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm, "wait_exponential", lambda **kwargs: wait_none())
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(503, text="sensitive provider response and contract text")
    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            with pytest.raises(llm._Retryable):
                await client.complete_json("system", "confidential contract")
    asyncio.run(run())
    assert len(requests) == 3
    assert "HTTP_503" in caplog.text
    assert "sensitive" not in caplog.text and "confidential" not in caplog.text
    assert "provider.invalid" not in caplog.text
