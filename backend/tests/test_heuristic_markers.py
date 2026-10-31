import uuid

import pytest

from app.models import RiskRule
from app.services.analyzer import (
    _CRITICAL_PATTERNS, _DOMAIN_GUARDS, _MARKER_EXCEPTIONS, RuleContext, _is_noise, evaluate_heuristic,
)
from app.services.retrieval import RetrievedChunk


def _marked(rule_id: str, text: str) -> bool:
    exception = _MARKER_EXCEPTIONS.get(rule_id)
    return bool(_CRITICAL_PATTERNS[rule_id].search(text)) and not (exception and exception.search(text))


@pytest.mark.parametrize("rule_id, text", [
    ("defect_fix_deadline", "Поставщик обязан устранить недостатки Товара в течение 1 (одного) дня с момента устного уведомления."),
    ("defect_fix_deadline", "Поставщик устраняет недостатки в течение 24 (двадцати четырёх) часов с момента получения акта."),
    ("defect_fix_deadline", "Недостатки устраняются в течение 2 рабочих дней."),
    ("unreasonable_penalty", "Поставщик уплачивает штраф в размере 10 % от цены Контракта."),
    ("unreasonable_penalty", "Поставщик уплачивает штраф в размере 15% от цены Контракта."),
    ("unreasonable_penalty", "Штраф устанавливается в фиксированном размере 10 (десяти) процентов цены Контракта."),
    ("uncapped_liability", "Поставщик возмещает убытки в полном объёме сверх неустойки."),
    ("uncapped_liability", "Ответственность Поставщика не ограничивается ценой Контракта."),
    ("brand_without_equivalent", "Ноутбук Lenovo ThinkPad E16, эквивалент не допускается."),
    ("brand_without_equivalent", "Поставка эквивалента не допускается."),
    ("unconditional_bg_claim", "Заказчик вправе в бесспорном порядке удержать всю сумму обеспечения."),
    ("unconditional_bg_claim", "Заказчик предъявляет требование об уплате 100 % суммы банковской гарантии."),
    ("rnp_short_cure_period", "Решение Заказчика об одностороннем отказе вступает в силу через 3 (три) дня с даты его направления."),
    ("rnp_short_cure_period", "Решение об одностороннем отказе вступает в силу с момента направления уведомления Поставщику."),
    ("short_delivery_time", "Поставка Товара осуществляется в течение 2 (двух) рабочих дней с даты заключения Контракта."),
    ("experience_restricted_44_223", "Опыт подтверждается исключительно контрактами, заключёнными по 44-ФЗ или 223-ФЗ."),
])
def test_critical_marker_found(rule_id, text):
    assert _marked(rule_id, text)


@pytest.mark.parametrize("rule_id, text", [
    ("defect_fix_deadline", "Поставщик устраняет недостатки в течение 13 рабочих дней с даты уведомления."),
    ("defect_fix_deadline", "Заказчик незамедлительно уведомляет Поставщика о выявленных недостатках."),
    ("unreasonable_penalty", "Поставщик уплачивает штраф в размере 0,1% от цены Контракта."),
    ("unreasonable_penalty", "Поставщик уплачивает штраф в размере 5 000 рублей."),
    ("uncapped_liability", "Для проверки Товара Заказчик вправе привлекать экспертов без ограничения срока."),
    ("brand_without_equivalent", "Ноутбук Lenovo ThinkPad E16 или эквивалент с параметрами эквивалентности согласно ТЗ."),
    ("brand_without_equivalent", "Товар с параметрами модели ThinkPad, эквивалент допускается."),
    ("unconditional_bg_claim", "Оплата производится в размере 100% от цены Контракта после приёмки."),
    ("rnp_short_cure_period", "Сторона обязана известить другую Сторону о форс-мажоре с момента направления уведомления."),
    ("rnp_short_cure_period", "Решение об одностороннем отказе вступает в силу через 10 (десять) дней с даты уведомления."),
    ("short_delivery_time", "Поставка Товара осуществляется в течение 15 рабочих дней с даты заключения Контракта."),
])
def test_critical_marker_not_found(rule_id, text):
    assert not _marked(rule_id, text)


@pytest.mark.parametrize("rule_id, text, expected", [
    ("contract_security_excessive", "Поставщик предоставляет обеспечение исполнения Контракта в размере 30 (тридцати) процентов от НМЦК.", True),
    ("contract_security_excessive", "Размер обеспечения исполнения контракта составляет 20 % от начальной цены.", True),
    ("contract_security_excessive", "Обеспечение заявки устанавливается в размере 1% от НМЦК.", False),
    ("national_regime", "Установлены запреты и ограничения в соответствии с ПП РФ от 23.12.2024 № 1875.", True),
    ("national_regime", "Применяется национальный режим.", True),
    ("national_regime", "Цена контракта составляет 1875000 рублей.", False),
])
def test_domain_guards(rule_id, text, expected):
    assert bool(_DOMAIN_GUARDS[rule_id].search(text)) is expected


def test_ocr_noise_is_detected():
    assert _is_noise("322 486 |МАОУ СОШ № 34 г.")
    assert not _is_noise("Поставщик уплачивает штраф в размере 10 % от цены Контракта 1 000 000 рублей.")


def _rule(rule_id: str, severity: str = "RED") -> RiskRule:
    return RiskRule(id=rule_id, law_type="44-FZ", category="Сроки", severity=severity, title="Сжатый срок устранения недостатков",
                    description="Срок устранения недостатков нереалистичен", semantic_query="устранение недостатков срок",
                    llm_prompt="Проверь срок.\nРекомендация: увеличить срок до 10 рабочих дней", legal_reference="ст. 34 44-ФЗ")


def _context(rule: RiskRule, *texts: str) -> RuleContext:
    return RuleContext(rule, [RetrievedChunk(uuid.uuid4(), i, 1, 1, None, t, 0.03 - i * 0.01, True) for i, t in enumerate(texts)])


def test_marker_quote_is_the_marked_sentence():
    text = ("Поставщик обязан устранить недостатки, выявленные при приёмке Товара. "
            "Недостатки устраняются в течение 1 (одного) дня с момента устного уведомления Заказчика.")
    [draft] = evaluate_heuristic([_context(_rule("defect_fix_deadline"), text)], [])
    assert draft.severity == "RED" and draft.confidence == 0.7
    assert "1 (одного) дня" in draft.exact_quote
    assert draft.counter_proposal == "увеличить срок до 10 рабочих дней"


def test_marker_found_in_less_relevant_chunk():
    first = "Поставщик обязан устранить недостатки Товара в сроки, согласованные Сторонами в акте."
    second = "Замена некачественного Товара производится в течение 24 (двадцати четырёх) часов."
    [draft] = evaluate_heuristic([_context(_rule("defect_fix_deadline"), first, second)], [])
    assert draft.severity == "RED" and "24 (двадцати четырёх) часов" in draft.exact_quote


def test_marker_split_across_sentences_is_not_critical():

    text = "Недостатки устраняются в течение 13 рабочих дней с даты уведомления. Срок продлевается по соглашению Сторон."
    [draft] = evaluate_heuristic([_context(_rule("defect_fix_deadline"), text)], [])
    assert draft.severity == "YELLOW"


def test_brand_with_equivalent_is_not_critical():
    text = "Ноутбук Lenovo ThinkPad E16 или эквивалент с параметрами эквивалентности согласно техническому заданию."
    [draft] = evaluate_heuristic([_context(_rule("brand_without_equivalent"), text)], [])
    assert draft.severity == "YELLOW"


def test_marker_does_not_raise_non_red_rule():
    text = "Недостатки устраняются в течение 1 (одного) дня с момента устного уведомления Заказчика."
    [draft] = evaluate_heuristic([_context(_rule("defect_fix_deadline", severity="YELLOW"), text)], [])
    assert draft.severity == "YELLOW" and "1 (одного) дня" in draft.exact_quote


def test_ocr_noise_is_not_quoted():
    text = "322 486 |МАОУ СОШ № 34 г. Томск. Поставщик устраняет недостатки Товара в срок, указанный в акте устранения недостатков."
    [draft] = evaluate_heuristic([_context(_rule("defect_fix_deadline"), text)], [])
    assert "МАОУ" not in draft.exact_quote
