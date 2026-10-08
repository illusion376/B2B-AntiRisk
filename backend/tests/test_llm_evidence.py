"""LLM protocol/provenance tests; model responses are controlled fixtures, not model accuracy tests."""
import asyncio
from copy import deepcopy
import uuid

import pytest

from app.models import RiskRule
from app.services import analyzer
from app.services.analyzer import RuleContext, _build_drafts
from app.services.retrieval import RetrievedChunk

RISK_TEXT = "Поставщик уплачивает штраф в размере 10 процентов за каждый день просрочки поставки."
SAFE_TEXT = "Срок оплаты составляет 7 рабочих дней после подписания акта приёмки товара."


def rule():
    return RiskRule(id="payment_terms", law_type="ALL", category="Оплата", severity="RED",
                    title="Неблагоприятные условия оплаты", description="Неблагоприятные условия оплаты",
                    semantic_query="срок оплаты штраф", llm_prompt="Проверь размер штрафа и срок оплаты.")


def chunk(text=RISK_TEXT, page=1):
    return RetrievedChunk(uuid.uuid4(), 0, page, page, "4. Оплата › п. 4.1", text, 0.1, True)


def pages(*texts):
    return [{"page_number": page, "words": [[index * 10, 0, index * 10 + 9, 12, word, 0]
                                             for index, word in enumerate(text.split())]}
            for page, text in enumerate(texts, start=1)]


def risk_answer(quote=RISK_TEXT):
    return {
        "verdict": "RISK", "explanation": "Высокий ежедневный штраф.", "evidence": [],
        "issues": [{"fragment": "F1", "quote": quote, "severity": "RED", "summary": "Высокий штраф",
                    "comment": "Размер ежедневного штрафа создаёт риск для поставщика.",
                    "recommendation": "Согласуйте уменьшение ежедневного штрафа.", "confidence": 0.9}],
    }


def ok_answer(quote=SAFE_TEXT):
    return {"verdict": "OK", "issues": [], "evidence": [{"fragment": "F1", "quote": quote}],
            "explanation": "В процитированном условии срок оплаты не превышает 7 рабочих дней."}


def evaluate(answer, text=RISK_TEXT, candidates=None, document_pages=None):
    checking = rule()
    context = RuleContext(checking, candidates if candidates is not None else [chunk(text)])
    return _build_drafts(checking, context, answer, document_pages if document_pages is not None else pages(text))


@pytest.mark.parametrize("answer", [
    {}, {"verdict": "TYPO"}, {"verdict": "OK", "issues": [], "evidence": [], "explanation": "Нет рисков"},
    {"verdict": "RISK", "issues": [], "evidence": [], "explanation": "Есть риск"},
    {"verdict": "NOT_FOUND", "issues": [], "evidence": [], "explanation": ""},
    {"verdict": "NOT_FOUND", "issues": [], "evidence": [{"fragment": "F1", "quote": SAFE_TEXT}], "explanation": "Нет"},
    {**risk_answer(), "unexpected": "extra field"},
])
def test_malformed_results_never_turn_into_confirmed_outcomes(answer):
    result = evaluate(answer)
    assert len(result) == 1
    assert result[0].severity == "UNKNOWN"
    assert result[0].source == "ERROR"
    assert result[0].exact_quote is None and not result[0].quote_verified


@pytest.mark.parametrize("key,value", [
    ("severity", "GREEN"), ("summary", 123), ("comment", " "), ("recommendation", None),
    ("confidence", "0.9"), ("confidence", 1.2), ("confidence", float("nan")),
    ("fragment", "fragment 1"), ("fragment", "F0"), ("quote", 123),
])
def test_issue_fields_are_validated_before_drafts(key, value):
    answer = risk_answer()
    answer["issues"][0][key] = value
    assert evaluate(answer)[0].severity == "UNKNOWN"


def test_valid_risk_keeps_exact_source_evidence_and_confidence():
    finding = evaluate(risk_answer())[0]
    assert finding.severity == "RED" and finding.source == "LLM"
    assert finding.exact_quote == RISK_TEXT and finding.quote_verified
    assert finding.page_number == 1 and finding.highlights
    assert finding.confidence == 0.9


def test_ok_requires_and_keeps_verified_evidence():
    finding = evaluate(ok_answer(), SAFE_TEXT)[0]
    assert finding.severity == "GREEN"
    assert finding.exact_quote == SAFE_TEXT and finding.quote_verified and finding.highlights
    assert finding.short_description == "Риск не выявлен в проверенных фрагментах"


@pytest.mark.parametrize("answer", [risk_answer(""), risk_answer("штраф"), ok_answer(""), ok_answer("Срок оплаты")])
def test_missing_or_meaningless_evidence_means_unknown(answer):
    finding = evaluate(answer)[0]
    assert finding.severity == "UNKNOWN" and not finding.quote_verified
    assert finding.exact_quote is None and finding.highlights == []


def test_not_found_and_missing_candidates_are_unknown():
    answer = {"verdict": "NOT_FOUND", "issues": [], "evidence": [], "explanation": "Нужное условие не найдено."}
    assert evaluate(answer)[0].severity == "UNKNOWN"
    assert evaluate(risk_answer(), candidates=[])[0].severity == "UNKNOWN"


@pytest.mark.parametrize("verdict", ["RISK", "OK"])
def test_quote_real_elsewhere_does_not_validate_wrong_fragment(verdict):
    answer = risk_answer(SAFE_TEXT) if verdict == "RISK" else ok_answer()
    # Both texts exist on the same page, but F1 contains only the risk text.
    finding = evaluate(answer, candidates=[chunk(RISK_TEXT), chunk(SAFE_TEXT)],
                       document_pages=pages(f"{RISK_TEXT} {SAFE_TEXT}"))[0]
    assert finding.severity == "UNKNOWN" and not finding.quote_verified


def test_nonexistent_fragment_is_rejected_instead_of_defaulting_to_first():
    answer = risk_answer()
    answer["issues"][0]["fragment"] = "F99"
    assert evaluate(answer)[0].severity == "UNKNOWN"


def test_adding_risk_by_dropping_negation_is_not_confirmed():
    actual = "Заказчик не вправе расторгнуть договор без письменного уведомления поставщика."
    fabricated = "Заказчик вправе расторгнуть договор без письменного уведомления поставщика."
    finding = evaluate(risk_answer(fabricated), actual)[0]
    assert finding.severity == "UNKNOWN" and not finding.quote_verified
    assert finding.exact_quote is None


def test_changed_payment_number_does_not_confirm_ok():
    actual = SAFE_TEXT.replace("7 рабочих", "70 рабочих")
    finding = evaluate(ok_answer(), actual)[0]
    assert finding.severity == "UNKNOWN" and not finding.quote_verified


def test_wrong_page_cannot_confirm_quote_even_if_candidate_text_matches():
    finding = evaluate(risk_answer(), candidates=[chunk(RISK_TEXT, page=1)],
                       document_pages=pages(SAFE_TEXT, RISK_TEXT))[0]
    assert finding.severity == "UNKNOWN" and not finding.quote_verified


def test_one_unsupported_issue_does_not_discard_a_separate_verified_risk():
    answer = risk_answer()
    second = deepcopy(answer["issues"][0])
    second["quote"] = "Заказчик может изменить все условия договора по своему усмотрению."
    answer["issues"].append(second)
    assert [result.severity for result in evaluate(answer)] == ["RED", "UNKNOWN"]


def test_client_initialization_failure_yields_unknown_without_changing_mode(monkeypatch):
    class BrokenClient:
        def __init__(self): raise RuntimeError("Unavailable")
    monkeypatch.setattr(analyzer, "LLMClient", BrokenClient)
    finding = asyncio.run(analyzer.evaluate_with_llm([RuleContext(rule(), [chunk()])], pages(RISK_TEXT), "contract.pdf", "44-FZ"))[0]
    assert finding.severity == "UNKNOWN" and finding.source == "ERROR"


def test_nli_inference_error_does_not_silently_switch_to_keyword(monkeypatch):
    from app.services import nli
    class BrokenClassifier:
        def predict(self, pairs): raise RuntimeError("Unavailable")
    monkeypatch.setattr(nli, "get_nli_classifier", lambda: BrokenClassifier())
    finding = analyzer.evaluate_nli([RuleContext(rule(), [chunk()])], pages(RISK_TEXT))[0]
    assert finding.severity == "UNKNOWN" and finding.source == "ERROR"
