import uuid
import numpy as np
import pytest

from app.models import RiskRule
from app.services.analyzer import FindingDraft
from app.services.dedup import (
    are_duplicate_findings,
    merge_duplicate_drafts,
    merge_two_drafts,
    quote_overlap_ratio,
)
from app.services.retrieval import (
    RetrievedChunk,
    apply_mmr,
    compute_chunk_similarity,
)


def _make_rule(rule_id: str, title: str, severity: str = "YELLOW", legal: str = "44-ФЗ") -> RiskRule:
    return RiskRule(
        id=rule_id,
        law_type="44-FZ",
        category="Ответственность",
        severity=severity,
        title=title,
        description=f"Описание {title}",
        semantic_query="штраф пени неустойка",
        llm_prompt=f"Проверь {title}",
        legal_reference=legal,
    )


def _make_draft(
    rule: RiskRule,
    severity: str,
    clause: str | None,
    quote: str | None,
    comment: str,
    page: int = 1,
    confidence: float = 0.8,
    highlights: list | None = None,
    counter: str | None = None,
) -> FindingDraft:
    return FindingDraft(
        rule=rule,
        severity=severity,
        title=rule.title,
        short_description=rule.title,
        comment=comment,
        counter_proposal=counter,
        page_number=page,
        clause=clause,
        exact_quote=quote,
        highlights=highlights or [{"x": 10, "y": 20}],
        quote_verified=True,
        confidence=confidence,
        source="LLM",
    )


# ============================================================================
# Тесты Уровня 1.А: Кросс-правиловая дедупликация (Cross-Rule Merging)
# ============================================================================

def test_quote_overlap_ratio():
    q1 = "Поставщик уплачивает Заказчику штраф в размере 10% от цены Контракта за каждый день просрочки"
    q2 = "Поставщик уплачивает Заказчику штраф в размере 10% от цены Контракта за каждый день нарушения"
    # Почти одинаковые цитаты: пересечение > 80%
    ratio = quote_overlap_ratio(q1, q2)
    assert ratio >= 0.70

    q3 = "Срок оплаты товаров составляет не более 7 рабочих дней с даты подписания документа о приемке"
    # Совершенно разные цитаты
    assert quote_overlap_ratio(q1, q3) < 0.20


def test_are_duplicate_by_same_clause():
    rule1 = _make_rule("uncapped_liability", "Неограниченная ответственность", "YELLOW")
    rule2 = _make_rule("unreasonable_penalty", "Несоразмерный штраф", "RED")

    d1 = _make_draft(rule1, "YELLOW", "6.2", "В случае просрочки поставщик платит пеню 1%", "Комментарий 1", page=3)
    d2 = _make_draft(rule2, "RED", "6.2", "В случае просрочки поставщик платит пеню 1% без ограничения", "Комментарий 2", page=3)

    assert are_duplicate_findings(d1, d2) is True


def test_are_duplicate_by_overlapping_quote():
    rule1 = _make_rule("uncapped_liability", "Неограниченная ответственность", "YELLOW")
    rule2 = _make_rule("unreasonable_penalty", "Несоразмерный штраф", "RED")

    # Пункты не указаны или слегка различаются, но цитата одна и та же
    q = "Заказчик удерживает неустойку из обеспечения исполнения контракта в безусловном порядке"
    d1 = _make_draft(rule1, "YELLOW", None, q, "Риск удержания", page=4)
    d2 = _make_draft(rule2, "RED", "раздел 8", q + " без согласия поставщика", "Штраф", page=4)

    assert are_duplicate_findings(d1, d2) is True


def test_not_duplicate_for_different_clauses_and_quotes():
    rule1 = _make_rule("uncapped_liability", "Неограниченная ответственность", "RED")
    rule2 = _make_rule("payment_delay", "Задержка оплаты", "YELLOW")

    d1 = _make_draft(rule1, "RED", "6.2", "Штраф составляет 5% в день", "Штраф", page=3)
    d2 = _make_draft(rule2, "YELLOW", "4.1", "Оплата производится в течение 60 дней", "Оплата", page=2)

    assert are_duplicate_findings(d1, d2) is False


def test_merge_two_drafts_combines_attributes():
    rule1 = _make_rule("uncapped_liability", "Неограниченная ответственность", "YELLOW", "ст. 34 44-ФЗ")
    rule2 = _make_rule("unreasonable_penalty", "Несоразмерный штраф", "RED", "ч. 6 ст. 34 44-ФЗ")

    box1 = {"x": 10, "y": 20, "w": 50, "h": 10}
    box2 = {"x": 10, "y": 35, "w": 50, "h": 10}

    d1 = _make_draft(
        rule1, "YELLOW", "6", "Поставщик платит штраф 10% в день",
        "Штраф не ограничен суммой контракта", page=5, confidence=0.75,
        highlights=[box1], counter="Установить предел ответственности"
    )
    d2 = _make_draft(
        rule2, "RED", "6.2", "Поставщик платит штраф 10% в день от полной цены контракта",
        "Размер штрафа превышает пределы ПП РФ 1042", page=5, confidence=0.92,
        highlights=[box2], counter="Снизить размер штрафа"
    )

    merged = merge_two_drafts(d1, d2)

    # Максимальная критичность RED выбрана
    assert merged.severity == "RED"
    # Более точный пункт договора (с точкой) выбран
    assert merged.clause == "6.2"
    # Более длинная цитата выбрана
    assert "от полной цены контракта" in merged.exact_quote
    # Подсветки объединены
    assert len(merged.highlights) == 2
    # Комментарии содержат информацию об обоих рисках
    assert "Размер штрафа превышает пределы" in merged.comment
    assert "Неограниченная ответственность" in merged.comment
    # Рекомендации объединены
    assert "Снизить размер штрафа" in merged.counter_proposal
    assert "Установить предел ответственности" in merged.counter_proposal
    # Максимальная уверенность выбрана
    assert merged.confidence == 0.92


def test_merge_duplicate_drafts_in_list():
    rule1 = _make_rule("r1", "Правило 1", "YELLOW")
    rule2 = _make_rule("r2", "Правило 2", "RED")
    rule3 = _make_rule("r3", "Правило 3 (другое)", "LOW")

    d1 = _make_draft(rule1, "YELLOW", "5.1", "Цитата о штрафе 5%", "Комментарий 1", page=2)
    d2 = _make_draft(rule2, "RED", "5.1", "Цитата о штрафе 5%", "Комментарий 2", page=2)
    d3 = _make_draft(rule3, "LOW", "8.3", "Иное условие приемки", "Комментарий 3", page=7)

    green_draft = FindingDraft(
        rule=_make_rule("r4", "Правило 4", "GREEN"),
        severity="GREEN",
        title="Правило 4",
        short_description="Без риска",
        comment="Рисков нет",
        page_number=1,
    )

    drafts = [d1, d2, d3, green_draft]
    merged = merge_duplicate_drafts(drafts)

    # d1 и d2 объединились в одну карточку, d3 и green остались
    assert len(merged) == 3
    # Первая карточка стала RED
    assert merged[0].severity == "RED"
    assert merged[0].clause == "5.1"
    # Третья карточка осталась GREEN
    assert merged[2].severity == "GREEN"


# ============================================================================
# Тесты Уровня 1.Б: MMR (Maximal Marginal Relevance) при отборе чанков
# ============================================================================

def test_compute_chunk_similarity_embeddings():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    c1 = RetrievedChunk(uuid.uuid4(), 1, 1, 1, "п. 1", "Текст 1", 0.03, True, embedding=v1)
    c2 = RetrievedChunk(uuid.uuid4(), 2, 1, 1, "п. 2", "Текст 2", 0.02, True, embedding=v2)
    c3 = RetrievedChunk(uuid.uuid4(), 3, 2, 2, "п. 3", "Текст 3", 0.01, True, embedding=v3)

    assert pytest.approx(compute_chunk_similarity(c1, c2), 0.01) == 1.0
    assert pytest.approx(compute_chunk_similarity(c1, c3), 0.01) == 0.0


def test_compute_chunk_similarity_text_fallback():
    # Без эмбеддингов: оценивается сходство текста
    t1 = "Форма заявки на участие в открытом конкурсе в электронной форме Приложение № 1 к Контракту"
    t2 = "Форма заявки на участие в открытом конкурсе в электронной форме Приложение № 2 к Контракту"
    t3 = "Ответственность сторон: при нарушении сроков поставщик выплачивает неустойку 0.1%"

    c1 = RetrievedChunk(uuid.uuid4(), 1, 1, 1, "п. 1", t1, 0.03, True)
    c2 = RetrievedChunk(uuid.uuid4(), 2, 1, 1, "п. 2", t2, 0.02, True)
    c3 = RetrievedChunk(uuid.uuid4(), 3, 2, 2, "п. 3", t3, 0.01, True)

    assert compute_chunk_similarity(c1, c2) >= 0.85
    assert compute_chunk_similarity(c1, c3) < 0.50


def test_apply_mmr_selects_diverse_chunks():
    # Ситуация из sammary.md: 3 повторяющихся приложения (дубли) и 1 другой раздел
    boilerplate1 = "Приложение № 1: Спецификация оборудования. Наименование товара, количество, единицы измерения."
    boilerplate2 = "Приложение № 2: Спецификация оборудования. Наименование товара, количество, единицы измерения повторно."
    boilerplate3 = "Приложение № 3: Спецификация оборудования. Наименование товара, количество, единицы измерения повторно."
    warranty_clause = "Раздел 7: Гарантийные обязательства. Поставщик гарантирует устранение дефектов в течение 24 часов."

    # Первые три имеют более высокий поисковый скор (0.035, 0.034, 0.033),
    # но являются почти полными дублями (сходство > 0.85)
    c1 = RetrievedChunk(uuid.uuid4(), 1, 10, 10, "Прил. 1", boilerplate1, score=0.035, fts_hit=True)
    c2 = RetrievedChunk(uuid.uuid4(), 2, 11, 11, "Прил. 2", boilerplate2, score=0.034, fts_hit=True)
    c3 = RetrievedChunk(uuid.uuid4(), 3, 12, 12, "Прил. 3", boilerplate3, score=0.033, fts_hit=True)
    c4 = RetrievedChunk(uuid.uuid4(), 4, 5, 5, "Раздел 7", warranty_clause, score=0.028, fts_hit=True)

    candidates = [c1, c2, c3, c4]
    # Отбираем top_k=2 с помощью MMR
    selected = apply_mmr(candidates, top_k=2, lambda_param=0.65, sim_threshold=0.80)

    assert len(selected) == 2
    # c1 выбран первым (наивысший скор)
    assert selected[0].id == c1.id
    # Второй выбран c4 (разнообразный раздел), а не дубликаты c2/c3
    assert selected[1].id == c4.id
