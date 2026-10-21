"""Server-side text model catalogue. The shared ProxyAPI key never reaches the browser."""
import re
import time
from threading import Lock

import httpx
from fastapi import HTTPException

from app.config import settings
from app.schemas import AnalysisModelOut, AnalysisModelsOut

PROVIDERS = {
    "openai": "OpenAI", "deepseek": "DeepSeek", "qwen": "Qwen",
    "anthropic": "Anthropic", "google": "Google",
}
# A usable baseline when /models is unavailable, including the three choices in the design.
# IDs are from https://proxyapi.ru/models/browse/text, not display names sent to the API.
FEATURED = {
    "openai/gpt-4.1-mini": ("GPT-4.1 mini", "Сбалансированная проверка договоров"),
    "deepseek/deepseek-chat": ("DeepSeek V3", "Анализ текста и логики условий"),
    "qwen/qwen-plus": ("Qwen Plus", "Альтернативная модель для анализа"),
    "openai/gpt-4.1": ("GPT-4.1", "Подробная проверка сложных документов"),
    "openai/gpt-5-mini": ("GPT-5 mini", "Проверка условий с рассуждением"),
    "anthropic/claude-sonnet-4-5": ("Claude Sonnet 4.5", "Анализ содержания и формулировок"),
    "anthropic/claude-haiku-4-5": ("Claude Haiku 4.5", "Быстрая проверка текста"),
    "google/gemini-3.5-flash": ("Gemini 3.5 Flash", "Проверка текста и содержания документов"),
}
_cache: dict[tuple, tuple[float, AnalysisModelsOut]] = {}
_lock = Lock()
_MODEL_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/@+\-]{0,199}$")
_NON_CHAT = re.compile(
    r"embed|rerank|moderation|whisper|transcri|\btts\b|audio|realtime|image|imagen|banana|"
    r"dall-e|sora|veo|video|ocr|computer-use|robotics", re.I,
)


def _is_chat_model(model_id: str) -> bool:
    vendor, _, name = model_id.lower().partition("/")
    if not _MODEL_ID.fullmatch(model_id) or _NON_CHAT.search(name):
        return False
    prefixes = {"openai": ("gpt-", "o1", "o3", "o4"), "deepseek": ("deepseek-",),
                "qwen": ("qwen", "qwq"), "anthropic": ("claude-",), "google": ("gemini-",)}
    return bool(name) and vendor in prefixes and name.startswith(prefixes[vendor])


def _option(model_id: str, *, available: bool) -> AnalysisModelOut:
    vendor, _, name = model_id.partition("/")
    label, description = FEATURED.get(model_id, (
        re.sub(r"\b(gpt|qwen|deepseek|claude|gemini|qwq)\b",
               lambda match: {"gpt": "GPT", "qwq": "QwQ"}.get(match[0], match[0].capitalize()),
               name.replace("-", " ")) if name else model_id, "Модель для анализа документов",
    ))
    return AnalysisModelOut(id=model_id, label=label, provider=PROVIDERS.get(vendor, "Другие"),
                            provider_id=vendor if vendor in PROVIDERS else "other",
                            description=description, available=available,
                            recommended=model_id == "openai/gpt-4.1-mini")


def model_catalog() -> AnalysisModelsOut:
    default = settings.llm_model.strip()
    enabled = settings.llm_enabled
    key = (settings.llm_base_url, settings.llm_api_key, default, enabled)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1].model_copy(deep=True)
        source = "fallback"
        warning = None
        ids = list(FEATURED)
        if enabled:
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(settings.llm_base_url.strip().rstrip("/") + "/models",
                                          headers={"Authorization": f"Bearer {settings.llm_api_key.strip()}"})
                    response.raise_for_status()
                    data = response.json()["data"]
                    ids = list(dict.fromkeys(item["id"] for item in data
                                             if isinstance(item, dict) and isinstance(item.get("id"), str)
                                             and _is_chat_model(item["id"])))
                    if not ids:
                        raise ValueError("No supported text models")
                source = "provider"
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                ids = list(FEATURED)
                warning = "Не удалось обновить список. Доступен основной набор моделей."
        default_available = source == "fallback" or default in ids
        if default and default not in ids:
            ids.append(default)
        rank = {value: index for index, value in enumerate(FEATURED)}
        ids.sort(key=lambda value: (rank.get(value, len(rank)), value))
        models = [_option(value, available=enabled and (value != default or default_available)) for value in ids]
        result = AnalysisModelsOut(default_model=default or None, models=models, source=source, warning=warning)
        # Short negative caching permits recovery without delaying every page or launch.
        _cache.clear()
        _cache[key] = (time.monotonic() + (300 if source == "provider" else 30), result)
        return result.model_copy(deep=True)


def analysis_model_or_422(requested: str | None, mode: str) -> str | None:
    if mode != "llm":
        return None
    if requested is None:
        return settings.llm_model.strip()
    model_id = requested.strip()
    if _MODEL_ID.fullmatch(model_id):
        option = next((item for item in model_catalog().models if item.id == model_id), None)
        if option and option.available:
            return model_id
    raise HTTPException(422, detail={"code": "analysis_model_unavailable", "analysis_model": model_id,
                                     "message": "Выбранная модель недоступна. Обновите список и выберите другую модель."})
