import asyncio
import json

import httpx
import pytest

from app.services import llm
from app.services.llm import LLMClient, LLMError, parse_json_response


@pytest.fixture(autouse=True)
def proxy_key(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_api_key", "test-proxy-key")
    client_type = httpx.AsyncClient

    def unexpected_request(request):
        raise AssertionError("Test must supply a mock provider response")

    def mock_client(**kwargs):
        # No real transports or machine proxy settings are needed in these unit tests.
        kwargs.setdefault("transport", httpx.MockTransport(unexpected_request))
        return client_type(**kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", mock_client)


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


@pytest.mark.parametrize("model", [
    "gpt-5-mini", "openai/gpt-5-mini", "gpt-5-nano", "gpt-5-2025-08-07",
    "openai/gpt-5.1", "o1", "openai/o3", "o4-mini",
])
def test_reasoning_models_use_supported_request_parameters(monkeypatch, model):
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_model", model)
    monkeypatch.setattr(llm.settings, "llm_max_tokens", 8192)
    monkeypatch.setattr(llm.settings, "llm_reasoning_effort", "low")

    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == model
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        assert payload["max_completion_tokens"] == 8192
        assert payload["reasoning_effort"] == "low"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]})

    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            assert await client.complete_json("Return JSON", "Check") == {"ok": True}
    asyncio.run(run())


@pytest.mark.parametrize("model", ["qwen2.5:7b-instruct", "gpt-4o-mini", "anthropic/claude-sonnet-4-6"])
def test_other_models_keep_configured_sampling_and_token_limit(monkeypatch, model):
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_model", model)
    monkeypatch.setattr(llm.settings, "llm_temperature", 0.2)
    monkeypatch.setattr(llm.settings, "llm_max_tokens", 1500)

    def handler(request):
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 1500
        assert "max_completion_tokens" not in payload
        assert "reasoning_effort" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": '{}'}, "finish_reason": "stop"}]})

    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            assert await client.complete_json("Return JSON", "Check") == {}
    asyncio.run(run())


def test_truncated_response_is_not_accepted_or_retried_with_same_budget(monkeypatch, caplog):
    from tenacity import wait_none
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm, "wait_exponential", lambda **kwargs: wait_none())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"verdict":"OK"}'}, "finish_reason": "length"}]})

    async def run():
        async with LLMClient() as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            with pytest.raises(llm.LLMOutputLimitError, match="LLM_MAX_TOKENS"):
                await client.complete_json("system", "confidential contract")
    asyncio.run(run())
    assert len(requests) == 1
    assert "OUTPUT_TOKEN_LIMIT" in caplog.text
    assert "confidential" not in caplog.text


def test_analysis_schema_is_requested_in_strict_mode(monkeypatch):
    from app.services.analyzer import LLMResult
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_model", "openai/gpt-5-mini")
    monkeypatch.setattr(llm.settings, "llm_json_mode", True)
    schema = LLMResult.model_json_schema()
    answer = {"verdict": "NOT_FOUND", "issues": [], "evidence": [], "explanation": "Условие не найдено."}

    def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_schema", "json_schema": {
            "name": "risk_rule_result", "strict": True, "schema": schema,
        }}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}]})

    async def run():
        async with LLMClient(response_schema=schema) as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            assert await client.complete_json("Return JSON", "Check") == answer
    asyncio.run(run())


def test_schema_fallback_keeps_the_same_model_and_parses_json(monkeypatch):
    from tenacity import wait_none
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_model", "configured-model")
    monkeypatch.setattr(llm.settings, "llm_json_mode", True)
    monkeypatch.setattr(llm, "wait_exponential", lambda **kwargs: wait_none())
    formats = []

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "configured-model"
        response_format = payload.get("response_format", {}).get("type")
        formats.append(response_format)
        if response_format == "json_schema":
            return httpx.Response(400, json={"error": "Unsupported json_schema"})
        if response_format == "json_object":
            return httpx.Response(400, json={"error": "Unsupported response_format"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]})

    async def run():
        async with LLMClient(response_schema={"type": "object"}) as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            assert await client.complete_json("Return JSON", "Check") == {"ok": True}
            assert await client.complete_json("Return JSON", "Check again") == {"ok": True}
    asyncio.run(run())
    assert formats == ["json_schema", "json_object", None, None]


def test_concurrent_schema_rejections_do_not_disable_supported_json_mode(monkeypatch):
    from tenacity import wait_none
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(llm.settings, "llm_json_mode", True)
    monkeypatch.setattr(llm, "wait_exponential", lambda **kwargs: wait_none())

    async def run():
        schema_requests = []
        all_started = asyncio.Event()

        async def handler(request):
            response_format = json.loads(request.content).get("response_format", {}).get("type")
            if response_format == "json_schema":
                schema_requests.append(request)
                if len(schema_requests) == 3:
                    all_started.set()
                await all_started.wait()
                return httpx.Response(400, json={"error": "Unsupported json_schema"})
            assert response_format == "json_object"
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]})

        async with LLMClient(response_schema={"type": "object"}) as client:
            await client._client.aclose()
            client._client = httpx.AsyncClient(base_url="https://provider.invalid/v1", transport=httpx.MockTransport(handler))
            answers = await asyncio.wait_for(asyncio.gather(
                *(client.complete_json("Return JSON", f"Check {i}") for i in range(3)),
            ), timeout=2)
            assert answers == [{"ok": True}] * 3
            assert client._json_mode is True
    asyncio.run(run())
