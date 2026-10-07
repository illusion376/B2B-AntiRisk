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
    pass


def parse_json_response(content: str) -> dict:
    """Достаёт JSON-объект из ответа модели (в т. ч. обёрнутый в ```json ... ```)."""
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1)
    else:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start:end + 1]
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Модель вернула некорректный JSON: {content[:200]}") from exc
    if not isinstance(value, dict):
        raise LLMError("Ожидался JSON-объект")
    return value


class LLMClient:
    def __init__(self) -> None:
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
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((_Retryable, httpx.TransportError, LLMError)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, max=15),
            reraise=True,
        ):
            with attempt:
                content = await self._chat(system, user)
                return parse_json_response(content)
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
            raise _Retryable(f"LLM HTTP {response.status_code}")
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"LLM HTTP {response.status_code}: {response.text[:300]}", request=response.request, response=response
            )
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Неожиданный ответ LLM: {str(data)[:200]}") from exc
