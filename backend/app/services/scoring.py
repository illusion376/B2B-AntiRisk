"""Индекс риска 0–100 и итоговый цвет «светофора»."""
from collections.abc import Iterable


def risk_score(severities: Iterable[str]) -> int:
    """Насыщающаяся шкала: каждое красное замечание «съедает» 30% оставшегося запаса, жёлтое — 10%,
    низкий риск — 3%.

    0 красных и 0 жёлтых -> 0; 1 красное -> 30; 3 красных + 5 жёлтых -> 80; дальше растёт медленно к 100.
    """
    safe = 1.0
    for severity in severities:
        if severity == "RED":
            safe *= 0.7
        elif severity == "YELLOW":
            safe *= 0.9
        elif severity == "LOW":
            safe *= 0.97
    return round(100 * (1 - safe))


def traffic_light(severities: Iterable[str]) -> str:
    """RED / YELLOW / GREEN. Низкий риск светофор не окрашивает (во фронтенде он зелёный)."""
    values = set(severities)
    if "RED" in values:
        return "RED"
    if "YELLOW" in values:
        return "YELLOW"
    return "GREEN"
