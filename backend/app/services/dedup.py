from __future__ import annotations

"""Кросс-правиловая дедупликация замечаний (Cross-Rule Merging).

Объединяет замечания от разных правил, указывающие на один и тот же пункт договора
или содержащие пересекающиеся цитаты (>=70% пересечения слов).
"""
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.analyzer import FindingDraft

_SEVERITY_ORDER = {"RED": 0, "YELLOW": 1, "LOW": 2, "UNKNOWN": 3, "GREEN": 4}


def _severity_rank(sev: str) -> int:
    return _SEVERITY_ORDER.get(sev.upper(), 99)


def _stronger_severity(s1: str, s2: str) -> str:
    return s1 if _severity_rank(s1) <= _severity_rank(s2) else s2


def _tokenize_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d_]{3,}", text.lower().replace("ё", "е"))}


def quote_overlap_ratio(q1: str | None, q2: str | None) -> float:
    """Вычисляет коэффициент пересечения слов между двумя цитатами."""
    if not q1 or not q2:
        return 0.0
    words1 = _tokenize_words(q1)
    words2 = _tokenize_words(q2)
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    if intersection == 0:
        return 0.0
    min_len = min(len(words1), len(words2))
    jaccard = intersection / len(words1 | words2)
    overlap = intersection / min_len
    return max(overlap, jaccard)


def _clean_clause(clause: str | None) -> str | None:
    if not clause:
        return None
    c = clause.strip()
    c = re.sub(r"^(?:пп?\.?|раздел|статья)\s*", "", c, flags=re.IGNORECASE)
    return c.strip() or None


def are_duplicate_findings(d1: FindingDraft, d2: FindingDraft) -> bool:
    """Определяет, относятся ли два замечания к одному условию/фрагменту договора."""
    # Объединяем только подтверждённые или потенциальные риски
    if d1.severity not in ("RED", "YELLOW", "LOW") or d2.severity not in ("RED", "YELLOW", "LOW"):
        return False

    # 1. Проверка цитат: пересечение более чем на 70% слов
    overlap = quote_overlap_ratio(d1.exact_quote, d2.exact_quote)
    if overlap >= 0.70:
        return True

    # 2. Если одинаковый номер пункта договора (например, 6.2)
    c1 = _clean_clause(d1.clause)
    c2 = _clean_clause(d2.clause)
    if c1 and c2 and c1 == c2:
        # Если пункт детальный (содержит точку, например «6.2» или «4.1.3»)
        if "." in c1:
            if d1.page_number is None or d2.page_number is None or d1.page_number == d2.page_number:
                return True
        # Если пункт верхнего уровня (например, просто раздел «6»), требуем также частичного совпадения цитаты
        elif overlap >= 0.35:
            return True

    return False


def merge_two_drafts(d1: FindingDraft, d2: FindingDraft) -> FindingDraft:
    """Объединяет два замечания в одно с сохранением максимальной строгости."""
    # Выбираем первичный драфт (более строгий уровень риска, затем большая уверенность)
    rank1 = (_severity_rank(d1.severity), -(d1.confidence or 0.0))
    rank2 = (_severity_rank(d2.severity), -(d2.confidence or 0.0))
    primary, secondary = (d1, d2) if rank1 <= rank2 else (d2, d1)

    # Итоговый уровень критичности: наивысший (RED > YELLOW > LOW)
    merged_severity = _stronger_severity(d1.severity, d2.severity)

    # Объединение комментариев без дублирования
    merged_comment = primary.comment
    sec_rule_title = secondary.rule.title if secondary.rule else secondary.title
    sec_rule_law = f" ({secondary.rule.legal_reference})" if secondary.rule and secondary.rule.legal_reference else ""
    secondary_note = f"[Дополнительный риск: {sec_rule_title}{sec_rule_law}] {secondary.comment}".strip()
    if secondary.comment and secondary.comment not in merged_comment:
        merged_comment = f"{merged_comment}\n\n{secondary_note}"

    # Объединение рекомендаций
    merged_counter = primary.counter_proposal or secondary.counter_proposal
    if primary.counter_proposal and secondary.counter_proposal and secondary.counter_proposal not in primary.counter_proposal:
        merged_counter = f"{primary.counter_proposal}; {secondary.counter_proposal}"

    # Подсветки: объединяем уникальные координаты
    merged_highlights = list(primary.highlights)
    existing_boxes = {str(h) for h in merged_highlights}
    for h in secondary.highlights:
        if str(h) not in existing_boxes:
            merged_highlights.append(h)
            existing_boxes.add(str(h))

    # Выбираем более информативную/длинную цитату
    q1 = primary.exact_quote or ""
    q2 = secondary.exact_quote or ""
    merged_quote = q1 if len(q1) >= len(q2) else q2

    # Пункт договора: предпочитаем более точный пункт с точкой («6.2» вместо «6»)
    c1 = primary.clause
    c2 = secondary.clause
    merged_clause = c1 or c2
    if c1 and c2 and "." in c2 and "." not in c1:
        merged_clause = c2

    return type(primary)(
        rule=primary.rule,
        severity=merged_severity,
        title=primary.title,
        short_description=primary.short_description,
        comment=merged_comment,
        counter_proposal=merged_counter,
        page_number=primary.page_number or secondary.page_number,
        clause=merged_clause,
        exact_quote=merged_quote or None,
        highlights=merged_highlights,
        quote_verified=primary.quote_verified or secondary.quote_verified,
        confidence=max(primary.confidence or 0.0, secondary.confidence or 0.0),
        source=primary.source,
    )


def merge_duplicate_drafts(drafts: list[Any]) -> list[Any]:
    """Выполняет кросс-правиловую дедупликацию замечаний."""
    if not drafts:
        return []

    result: list[FindingDraft] = []
    for draft in drafts:
        if draft.severity not in ("RED", "YELLOW", "LOW"):
            result.append(draft)
            continue

        merged_into_existing = False
        for i, existing in enumerate(result):
            if existing.severity in ("RED", "YELLOW", "LOW") and are_duplicate_findings(existing, draft):
                result[i] = merge_two_drafts(existing, draft)
                merged_into_existing = True
                break

        if not merged_into_existing:
            result.append(draft)

    return result
