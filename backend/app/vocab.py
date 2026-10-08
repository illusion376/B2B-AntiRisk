"""Словарь API в терминах фронтенда (frontend/lib/types.ts) и перевод в значения БД.

В БД (database/init-db.sql) уровни хранятся как RED / YELLOW / GREEN (+ LOW для низкого риска),
статусы проверки — NEW / CONFIRMED / DISMISSED. Фронтенд оперирует critical / warning / low / ok
и unseen / accepted / dismissed. API говорит на языке фронтенда, перевод — только здесь.
"""
from typing import Literal

from fastapi import HTTPException

Severity = Literal["critical", "warning", "low", "unknown", "ok"]
RiskLevel = Literal["critical", "warning", "low"]
ReviewStatus = Literal["unseen", "accepted", "dismissed"]

SEVERITY_TO_API: dict[str, str] = {"RED": "critical", "YELLOW": "warning", "LOW": "low", "UNKNOWN": "unknown", "GREEN": "ok"}
SEVERITY_FROM_API: dict[str, str] = {v: k for k, v in SEVERITY_TO_API.items()}

REVIEW_TO_API: dict[str, str] = {"NEW": "unseen", "CONFIRMED": "accepted", "RESOLVED": "accepted", "DISMISSED": "dismissed"}
REVIEW_FROM_API: dict[str, str] = {"unseen": "NEW", "accepted": "CONFIRMED", "dismissed": "DISMISSED"}

# Порядок групп замечаний и сила риска (для сравнения уровней)
SEVERITY_ORDER = ["RED", "YELLOW", "LOW", "UNKNOWN", "GREEN"]
SEVERITY_RANK = {"RED": 3, "YELLOW": 2, "LOW": 1, "GREEN": 0}

SEVERITY_GROUP_LABELS = {  # как severityLabels во фронтенде
    "RED": "Критические замечания", "YELLOW": "Требуют внимания", "LOW": "Низкий риск", "UNKNOWN": "Недостаточно данных", "GREEN": "Без замечаний",
}
SEVERITY_SHORT_LABELS = {"RED": "Критично", "YELLOW": "Внимание", "LOW": "Низкий риск", "UNKNOWN": "Недостаточно данных", "GREEN": "Без замечаний"}
RISK_LEVEL_LABELS = {"RED": "Высокий риск", "YELLOW": "Средний риск", "LOW": "Низкий риск"}  # riskLabels
REVIEW_LABELS = {"NEW": "Не просмотрено", "CONFIRMED": "Принято", "RESOLVED": "Принято", "DISMISSED": "Отклонено"}


def weaker(a: str, b: str) -> str:
    """Менее критичный из двух уровней."""
    return a if SEVERITY_RANK.get(a, 0) <= SEVERITY_RANK.get(b, 0) else b


def parse_filter(value: str | None, mapping: dict[str, str], name: str) -> list[str] | None:
    """«critical,warning» -> ["RED", "YELLOW"]; неизвестное значение -> 422."""
    if not value:
        return None
    result = []
    for item in value.split(","):
        item = item.strip().lower()
        if item not in mapping:
            raise HTTPException(422, f"Недопустимое значение {name}: «{item}». Допустимо: {', '.join(mapping)}")
        result.append(mapping[item])
    return result
