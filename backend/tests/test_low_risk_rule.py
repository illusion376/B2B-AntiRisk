import re
import uuid
from pathlib import Path

from app.models import RiskRule
from app.services.analyzer import RuleContext, _build_drafts, evaluate_heuristic
from app.services.extraction import extract_pages
from app.services.retrieval import RetrievedChunk

MIGRATION = "010_low_risk_rule.sql"


def _migration_rule() -> RiskRule:
    candidates = [Path(__file__).resolve().parents[2] / "database" / "migrations" / MIGRATION,
                  Path("/app/migrations") / MIGRATION]
    sql = next(p for p in candidates if p.exists()).read_text(encoding="utf-8")
    values = re.findall(r"'((?:[^']|'')*)'", sql.split("VALUES", 1)[1])
    keys = ["id", "law_type", "category", "severity", "title", "description", "semantic_query", "llm_prompt",
            "legal_reference"]
    return RiskRule(**dict(zip(keys, values)))


def test_migration_adds_low_risk_rule():
    rule = _migration_rule()
    assert rule.id == "paper_only_notices" and rule.severity == "LOW"
    assert "LOW" in rule.llm_prompt and "Рекомендация:" in rule.llm_prompt


def _chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(uuid.uuid4(), 0, 1, 1, "9. Прочие условия › п. 9.3", text, 0.03, True)


def test_low_rule_caps_llm_severity(contract_pdf):
    """Уровень правила — верхняя граница: даже ответ модели «RED» даёт «Низкий риск»."""
    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    quote = "Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта за каждый день просрочки"
    answer = {"verdict": "RISK", "evidence": [], "explanation": "Найдено условие.", "issues": [{
        "fragment": "F1", "quote": quote, "severity": "RED", "summary": "Суть", "comment": "Обоснование",
        "recommendation": "Новая редакция", "confidence": 0.9}]}
    rule = _migration_rule()
    drafts = _build_drafts(rule, RuleContext(rule, [_chunk(f"6.2. {quote}.")]), answer, pages)
    assert [d.severity for d in drafts] == ["LOW"]


def test_low_rule_in_keyword_mode():
    rule = _migration_rule()
    text = ("9.3. Все уведомления, претензии и счета направляются Сторонами исключительно на бумажном носителе "
            "заказным письмом с уведомлением о вручении; электронная переписка юридической силы не имеет.")
    [draft] = evaluate_heuristic([RuleContext(rule, [_chunk(text)])], [])
    assert draft.severity == "LOW" and "бумажном носителе" in draft.exact_quote
