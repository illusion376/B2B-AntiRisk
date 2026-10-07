import uuid

from app.models import RiskRule
from app.services.analyzer import RuleContext, _build_drafts, evaluate_heuristic
from app.services.embeddings import _hash_embedding
from app.services.extraction import extract_pages
from app.services.llm import parse_json_response
from app.services.retrieval import RetrievedChunk
from app.services.scoring import risk_score, traffic_light


def _rule(severity="RED") -> RiskRule:
    return RiskRule(
        id="unreasonable_penalty", law_type="44-FZ", category="Штрафы и пени", severity=severity,
        title="Несоразмерная неустойка", description="Штрафы превышают установленные",
        semantic_query="размер пени штраф ответственность поставщика процент за день просрочки",
        llm_prompt="Проверь размер пени", legal_reference="ст. 34 44-ФЗ",
    )


def _chunk(content: str, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(uuid.uuid4(), 0, page, page, "6. Ответственность сторон › п. 6.2", content, 0.03, True)


def test_parse_json_response_variants():
    assert parse_json_response('```json\n{"verdict": "OK"}\n```') == {"verdict": "OK"}
    assert parse_json_response('Ответ: {"verdict": "RISK", "issues": []} конец') == {"verdict": "RISK", "issues": []}


def test_llm_answer_to_drafts(contract_pdf):
    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    chunk = _chunk("6.2. Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта ...")
    answer = {
        "verdict": "RISK",
        "issues": [{
            "fragment": "F1",
            "quote": "Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта за каждый день просрочки",
            "severity": "RED",
            "summary": "Размер штрафа не ограничен суммой контракта",
            "comment": "Пеня не ограничена",
            "recommendation": "Ограничить общий размер неустойки ценой контракта",
            "confidence": 0.9,
        }],
    }
    rule = _rule()
    drafts = _build_drafts(rule, RuleContext(rule, [chunk]), answer, pages)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.severity == "RED" and d.quote_verified and d.page_number == 1 and d.clause == "6.2"
    assert d.highlights and d.counter_proposal and d.confidence == 0.9

    ok = _build_drafts(rule, RuleContext(rule, [chunk]), {"verdict": "OK", "explanation": "Всё в норме"}, pages)
    assert ok[0].severity == "GREEN" and ok[0].comment == "Всё в норме"

    # Модель может понизить критичность, но не повысить жёлтое правило до красного
    yellow_rule = _rule("YELLOW")
    answer["issues"][0]["severity"] = "RED"
    raised = _build_drafts(yellow_rule, RuleContext(yellow_rule, [chunk]), answer, pages)
    assert raised[0].severity == "YELLOW"

    # Правило с низким риском: даже «RED» от модели остаётся низким риском
    low_rule = _rule("LOW")
    lowered = _build_drafts(low_rule, RuleContext(low_rule, [chunk]), answer, pages)
    assert lowered[0].severity == "LOW"
    # Модель понижает критическое правило до низкого риска
    answer["issues"][0]["severity"] = "LOW"
    assert _build_drafts(rule, RuleContext(rule, [chunk]), answer, pages)[0].severity == "LOW"
    answer["issues"][0]["severity"] = "RED"

    # Цитата, которой нет в документе: замечание остаётся, но помечено как непроверенное
    answer["issues"][0]["quote"] = "Совершенно другой текст, которого нет"
    unverified = _build_drafts(rule, RuleContext(rule, [chunk]), answer, pages)
    assert not unverified[0].quote_verified and unverified[0].confidence < 0.9


def test_heuristic_mode(contract_pdf):
    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    rule = _rule()
    chunk = _chunk("6.2. Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта за каждый день "
                   "просрочки исполнения обязательств, но не ограниченной общей суммой Контракта.")
    drafts = evaluate_heuristic([RuleContext(rule, [chunk]), RuleContext(_rule(), [])], pages)
    assert drafts[0].severity == "YELLOW" and drafts[0].source == "HEURISTIC" and drafts[0].quote_verified
    assert drafts[1].severity == "GREEN"


def test_hash_embedding_similarity():
    import numpy as np

    a = np.array(_hash_embedding("штраф за просрочку поставки товара", 1024))
    b = np.array(_hash_embedding("Поставщик уплачивает штрафы за просрочку", 1024))
    c = np.array(_hash_embedding("гарантийный срок производителя", 1024))
    assert len(a) == 1024 and abs(np.linalg.norm(a) - 1) < 1e-5
    assert a @ b > a @ c


def test_scoring():
    assert risk_score([]) == 0
    assert risk_score(["RED"]) == 30
    assert risk_score(["RED"] * 3 + ["YELLOW"] * 5 + ["GREEN"] * 12) == 80
    assert risk_score(["LOW"]) == 3
    assert traffic_light(["LOW", "GREEN"]) == "GREEN"  # низкий риск светофор не окрашивает
    assert traffic_light(["GREEN", "YELLOW"]) == "YELLOW"
    assert traffic_light(["GREEN"]) == "GREEN"


def test_evaluate_with_llm_handles_errors(contract_pdf, monkeypatch):
    import asyncio

    from app.services import analyzer

    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def complete_json(self, system, user):
            calls.append(user)
            if "СЛОМАННОЕ" in user:
                raise RuntimeError("provider down")
            return {"verdict": "OK", "issues": [], "explanation": "Нарушений нет"}

    monkeypatch.setattr(analyzer, "LLMClient", FakeClient)
    good, broken = _rule(), _rule()
    broken.title = "СЛОМАННОЕ правило"
    chunk = _chunk("6.2. Поставщик уплачивает штраф")
    drafts = asyncio.run(analyzer.evaluate_with_llm(
        [RuleContext(good, [chunk]), RuleContext(broken, [chunk]), RuleContext(_rule(), [])], pages, "doc.pdf", "44-FZ"))
    assert [d.severity for d in drafts] == ["GREEN", "YELLOW", "GREEN"]
    assert drafts[1].source == "ERROR"  # сбой одного правила не роняет весь документ
    assert len(calls) == 2  # правило без релевантных фрагментов в LLM не отправляется
    assert "44-ФЗ" in calls[0] and "[F1] (стр. 1" in calls[0]


def test_nli_evaluation_risk_detected(contract_pdf, monkeypatch):
    from unittest.mock import MagicMock
    from app.services import analyzer, nli

    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    rule = _rule()
    chunk = _chunk("6.2. Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта за каждый день "
                   "просрочки исполнения обязательств, но не ограниченной общей суммой Контракта.")

    fake_classifier = MagicMock()
    # Возвращаем высокий entailment для рискованного чанка
    fake_classifier.predict.return_value = [{"entailment": 0.88, "neutral": 0.08, "contradiction": 0.04}]
    monkeypatch.setattr(nli, "get_nli_classifier", lambda: fake_classifier)

    r2 = _rule()
    r2.id = "r2_no_chunks"
    drafts = analyzer.evaluate_nli([RuleContext(rule, [chunk]), RuleContext(r2, [])], pages)
    assert len(drafts) == 2
    assert drafts[0].severity == "RED"
    assert drafts[0].source == "NLI"
    assert drafts[0].quote_verified
    assert drafts[0].clause == "6.2"
    assert drafts[0].confidence == 0.88
    assert "Семантический NLI-анализ подтвердил риск" in drafts[0].comment
    assert drafts[1].severity == "GREEN"


def test_nli_evaluation_contradiction_ok(contract_pdf, monkeypatch):
    from unittest.mock import MagicMock
    from app.services import analyzer, nli

    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    rule = _rule()
    chunk = _chunk("6.2. Размер штрафа ограничен ценой контракта в строгом соответствии с 44-ФЗ.")

    fake_classifier = MagicMock()
    # Возвращаем высокий contradiction (риск опровергнут текстом)
    fake_classifier.predict.return_value = [{"entailment": 0.05, "neutral": 0.15, "contradiction": 0.80}]
    monkeypatch.setattr(nli, "get_nli_classifier", lambda: fake_classifier)

    drafts = analyzer.evaluate_nli([RuleContext(rule, [chunk])], pages)
    assert len(drafts) == 1
    assert drafts[0].severity == "GREEN"
    assert drafts[0].source == "NLI"
    assert "риск опровергнут" in drafts[0].comment


def test_nli_fallback_to_heuristic(contract_pdf, monkeypatch):
    from app.services import analyzer, nli

    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    rule = _rule()
    chunk = _chunk("6.2. Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости Контракта за каждый день "
                   "просрочки исполнения обязательств, но не ограниченной общей суммой Контракта.")

    def failing_classifier():
        raise RuntimeError("torch out of memory")

    monkeypatch.setattr(nli, "get_nli_classifier", failing_classifier)

    drafts = analyzer.evaluate_nli([RuleContext(rule, [chunk])], pages)
    assert len(drafts) == 1
    assert drafts[0].source == "HEURISTIC"  # откатился к эвристике
    assert drafts[0].quote_verified
