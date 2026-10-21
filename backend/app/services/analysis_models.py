"""Server-side text model catalogue. The shared ProxyAPI key never reaches the browser."""
import time
from threading import Lock

import httpx
from fastapi import HTTPException

from app.config import settings
from app.schemas import AnalysisModelOut, AnalysisModelsOut

PROVIDERS = {
    "openai": "OpenAI", "anthropic": "Anthropic", "deepseek": "DeepSeek",
}
# Only these three models can be selected for a new analysis.
# IDs are from https://proxyapi.ru/models/browse/text, not display names sent to the API.
FEATURED = {
    "openai/gpt-4.1-mini": ("GPT-4.1 mini", "Сбалансированная проверка договоров"),
    "anthropic/claude-sonnet-4-5": ("Claude Sonnet 4.5", "Анализ содержания и формулировок"),
    "deepseek/deepseek-v4-flash": ("DeepSeek V4 Flash", "Анализ текста и логики условий"),
}
_cache: dict[tuple, tuple[float, AnalysisModelsOut]] = {}
_lock = Lock()


def _default_model() -> str:
    configured = settings.llm_model.strip()
    return configured if configured in FEATURED else "openai/gpt-4.1-mini"


def _option(model_id: str, *, available: bool) -> AnalysisModelOut:
    vendor = model_id.partition("/")[0]
    label, description = FEATURED[model_id]
    return AnalysisModelOut(id=model_id, label=label, provider=PROVIDERS[vendor], provider_id=vendor,
                            description=description, available=available,
                            recommended=model_id == "openai/gpt-4.1-mini")


def model_catalog() -> AnalysisModelsOut:
    default = _default_model()
    enabled = settings.llm_enabled
    key = (settings.llm_base_url, settings.llm_api_key, default, enabled)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1].model_copy(deep=True)
        source = "fallback"
        warning = None
        available_ids: set[str] | None = None
        if enabled:
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(settings.llm_base_url.strip().rstrip("/") + "/models",
                                          headers={"Authorization": f"Bearer {settings.llm_api_key.strip()}"})
                    response.raise_for_status()
                    data = response.json()["data"]
                    if not isinstance(data, list):
                        raise ValueError("Invalid model catalogue")
                    available_ids = {item["id"] for item in data if isinstance(item, dict)
                                     and isinstance(item.get("id"), str) and item["id"] in FEATURED}
                source = "provider"
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                warning = "Не удалось обновить список. Доступен основной набор моделей."
        models = [_option(value, available=enabled and (available_ids is None or value in available_ids))
                  for value in FEATURED]
        result = AnalysisModelsOut(default_model=default or None, models=models, source=source, warning=warning)
        # Short negative caching permits recovery without delaying every page or launch.
        _cache.clear()
        _cache[key] = (time.monotonic() + (300 if source == "provider" else 30), result)
        return result.model_copy(deep=True)


def analysis_model_or_422(requested: str | None, mode: str) -> str | None:
    if mode != "llm":
        return None
    if requested is None:
        return _default_model()
    model_id = requested.strip()
    if model_id in FEATURED:
        option = next((item for item in model_catalog().models if item.id == model_id), None)
        if option and option.available:
            return model_id
    raise HTTPException(422, detail={"code": "analysis_model_unavailable", "analysis_model": model_id,
                                     "message": "Выбранная модель недоступна. Обновите список и выберите другую модель."})
