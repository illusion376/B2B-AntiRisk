import asyncio
import uuid

import pytest

from app.models import RiskRule
from app.services import analyzer
from app.services.analyzer import RuleContext
from app.services.retrieval import RetrievedChunk


def context(text, fts=True):
    rule = RiskRule(id="test", title="Условия оплаты", description="Потенциальный риск", severity="RED",
                    semantic_query="оплата ответственность", llm_prompt="Проверь условия", law_type="44-FZ")
    return RuleContext(rule, [RetrievedChunk(uuid.uuid4(), 0, 1, 1, None, text, 0.03, fts)])


@pytest.mark.parametrize("sensitivity", ["strict", "balanced", "sensitive"])
def test_llm_receives_sensitivity_without_relaxing_evidence_checks(monkeypatch, sensitivity):
    calls = []

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def complete_json(self, system, _user):
            calls.append(system)
            return {"verdict": "RISK", "issues": [{"fragment": "F1", "quote": "Этой цитаты не существует в настоящем документе.",
                "severity": "RED", "summary": "Риск", "comment": "Обоснование", "recommendation": "Проверить", "confidence": 0.99}],
                "evidence": [], "explanation": "Результат"}

    monkeypatch.setattr(analyzer, "LLMClient", Client)
    drafts = asyncio.run(analyzer.evaluate_with_llm([context("Оплата производится после приёмки документов.")], [], "Договор", None, sensitivity))
    assert len(calls) == 1 and analyzer.SENSITIVITY_INSTRUCTIONS[sensitivity] in calls[0]
    assert "дословно" in calls[0].lower()
    assert drafts[0].severity == "UNKNOWN" and not drafts[0].quote_verified


def test_keyword_sensitivity_changes_match_breadth_without_claiming_verified_violations():
    partial = context("Оплата производится после подписания акта приёмки товара.")
    assert analyzer.evaluate_heuristic([partial], [], "strict") == []
    balanced = analyzer.evaluate_heuristic([partial], [], "balanced")
    assert len(balanced) == 1 and balanced[0].severity == "YELLOW" and balanced[0].source == "HEURISTIC"
    semantic = context("Покупатель перечисляет вознаграждение после приёмки товара.", fts=False)
    assert analyzer.evaluate_heuristic([semantic], [], "balanced") == []
    assert len(analyzer.evaluate_heuristic([semantic], [], "sensitive")) == 1


def test_unknown_sensitivity_is_rejected_by_evaluators():
    with pytest.raises(ValueError):
        analyzer.evaluate_heuristic([], [], "typo")
    with pytest.raises(ValueError):
        asyncio.run(analyzer.evaluate_with_llm([], [], "Договор", None, "typo"))
