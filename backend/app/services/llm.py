"""Клиент OpenAI-совместимого chat/completions (Ollama, vLLM, YandexGPT, OpenRouter, OpenAI...)."""
import json
import logging
import re

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class _Retryable(Exception):
    def __init__(self, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(f"LLM HTTP {status_code}" if status_code is not None else "LLM retry requested")


def failure_code(error: BaseException) -> str:
    """Diagnostic code safe for logs: never includes URLs, bodies or contract text."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP_{error.response.status_code}"
    if isinstance(error, _Retryable) and error.status_code is not None:
        return f"HTTP_{error.status_code}"
    return type(error).__name__


def parse_json_response(content: str) -> dict:
    """Достаёт JSON-объект из ответа модели (в т. ч. обёрнутый в ```json ... ```)."""
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Модель не вернула текстовый JSON-ответ")
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1)
    else:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start:end + 1]
    try:
        value = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)
    except (json.JSONDecodeError, ValueError) as exc:
        # Contract text can be sensitive. Do not include response bodies in errors or logs.
        raise LLMError("Модель вернула некорректный JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("Ожидался JSON-объект")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("Non-finite JSON number")


class LLMClient:
    def __init__(self) -> None:
        if not settings.llm_base_url or not settings.llm_base_url.strip():
            raise LLMError("Для LLM-режима необходимо настроить LLM_BASE_URL")
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        self._client = httpx.AsyncClient(
            base_url=(settings.llm_base_url or "").rstrip("/"),
            headers=headers,
            timeout=settings.llm_timeout_s,
        )
        self._json_mode = settings.llm_json_mode

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def complete_json(self, system: str, user: str) -> dict:
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type((_Retryable, httpx.TransportError, LLMError)),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, max=15),
                reraise=True,
            ):
                with attempt:
                    content = await self._chat(system, user)
                    return parse_json_response(content)
        except Exception as exc:
            log.error("LLM request failed after retries: %s", failure_code(exc))
            raise
        raise LLMError("unreachable")

    async def _chat(self, system: str, user: str) -> str:
        payload: dict = {
            "model": settings.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = await self._client.post("/chat/completions", json=payload)
        if response.status_code == 400 and self._json_mode and "response_format" in response.text:
            # Провайдер не поддерживает json-режим — дальше просим JSON только промптом
            log.warning("LLM provider rejected response_format, disabling JSON mode")
            self._json_mode = False
            raise _Retryable()
        if response.status_code == 429 or response.status_code >= 500:
            raise _Retryable(response.status_code)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"LLM HTTP {response.status_code}", request=response.request, response=response
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            # Even a syntactically valid prefix cannot be trusted after token truncation.
            if choice.get("finish_reason") not in (None, "stop"):
                raise LLMError("Генерация ответа LLM не завершена успешно")
            message = choice["message"]
            if message.get("refusal"):
                raise LLMError("LLM отказалась выполнять проверку")
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMError("LLM не вернула текст ответа")
            return content
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise LLMError("Неожиданный формат ответа LLM-провайдера") from exc
