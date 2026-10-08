"""Выбор движка до постановки задачи в очередь и повторная проверка в воркере."""
from fastapi import HTTPException

from app.config import settings
from app.schemas import AnalysisMode, AnalysisModeOut, AnalysisModesOut


class AnalysisModeError(ValueError):
    def __init__(self, code: str, message: str, mode: str):
        super().__init__(message)
        self.detail = {"code": code, "message": message, "analysis_mode": mode}


def _llm_available() -> bool:
    return settings.llm_enabled and bool(settings.llm_model.strip())


def default_analysis_mode() -> AnalysisMode:
    if settings.analysis_engine == "auto":
        return "llm" if settings.llm_enabled else settings.heuristic_engine
    return settings.analysis_engine


def resolve_analysis_mode(requested: str | None = None) -> AnalysisMode:
    mode = default_analysis_mode() if requested is None else requested
    if mode not in ("llm", "nli", "keyword"):
        raise AnalysisModeError("invalid_analysis_mode", "Выберите режим llm, nli или keyword", mode)
    if mode == "llm" and not _llm_available():
        raise AnalysisModeError(
            "analysis_mode_unavailable",
            "LLM не настроена: администратору нужно указать LLM_BASE_URL и LLM_MODEL на сервере",
            mode,
        )
    return mode


def analysis_mode_or_422(requested: str | None = None) -> AnalysisMode:
    try:
        return resolve_analysis_mode(requested)
    except AnalysisModeError as exc:
        raise HTTPException(422, detail=exc.detail) from exc


def capabilities() -> AnalysisModesOut:
    # available означает наличие конфигурации, не результат запроса к провайдеру.
    # Модели NLI могут загружаться при первом запуске; сбой не меняет выбранный режим.
    return AnalysisModesOut(
        default_mode=default_analysis_mode(),
        configured_model=settings.llm_model if _llm_available() else None,
        modes=[
            AnalysisModeOut(id="llm", label="LLM", available=_llm_available(),
                            description="Анализ условий и правил языковой моделью через настроенный серверный API."),
            AnalysisModeOut(id="nli", label="NLI", available=True,
                            description="Локальная модель проверяет смысловое соответствие фрагментов правилам. Возможны неточные выводы."),
            AnalysisModeOut(id="keyword", label="Ключевые слова", available=True,
                            description="Предварительный поиск совпадений по словам. Не определяет наличие нарушения."),
        ],
    )
