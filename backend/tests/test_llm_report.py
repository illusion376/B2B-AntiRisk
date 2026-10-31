import uuid
from datetime import datetime
from unittest.mock import MagicMock

from docx import Document as DocxDocument

from app.models import RiskRule
from app.services import pipeline
from app.services.analyzer import FindingDraft
from app.services.dedup import merge_two_drafts
from app.services.reports.data import ReportData, ReportDocument, ReportFinding
from app.services.reports.docx_builder import DISCLAIMER, build_detailed


def _rule(rule_id: str, query: str = "обеспечение заявки размер") -> RiskRule:
    return RiskRule(id=rule_id, law_type="44-FZ", category="Обеспечение", severity="RED", title=rule_id,
                    description="Описание", semantic_query=query, llm_prompt="Проверь", legal_reference="ст. 44 44-ФЗ")


def test_rule_embedding_is_recomputed_when_query_text_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: calls.append(list(texts)) or [[0.1] * 3 for _ in texts])
    db = MagicMock()
    rule = _rule("bid_security_excessive")

    pipeline.ensure_rule_embeddings(db, [rule])
    pipeline.ensure_rule_embeddings(db, [rule])
    assert len(calls) == 1


    rule.semantic_query = "обеспечение заявки на участие в аукционе процент НМЦК"
    pipeline.ensure_rule_embeddings(db, [rule])
    assert calls[-1] == [rule.semantic_query]
    assert rule.embedding_model == pipeline.rule_embedding_key(rule)


def test_rule_embedding_cached_before_text_hash_is_refreshed(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: calls.append(list(texts)) or [[0.1] * 3 for _ in texts])
    rule = _rule("unreasonable_penalty")
    rule.query_embedding = [0.0] * 3
    rule.embedding_model = pipeline.settings.embedding_model_id
    pipeline.ensure_rule_embeddings(MagicMock(), [rule])
    assert calls == [[rule.semantic_query]]


def _draft(rule: RiskRule, severity: str, counter: str) -> FindingDraft:
    return FindingDraft(rule=rule, severity=severity, title=rule.title, short_description=rule.title, comment="Обоснование",
                        counter_proposal=counter, page_number=1, clause="6.2", exact_quote="Поставщик платит штраф 10%",
                        highlights=[], quote_verified=True, confidence=0.8, source="LLM")


def test_merged_recommendations_have_clean_punctuation():
    merged = merge_two_drafts(_draft(_rule("a"), "RED", "Снизить размер штрафа."),
                              _draft(_rule("b"), "YELLOW", "Установить предел ответственности;"))
    assert merged.counter_proposal == "Снизить размер штрафа; Установить предел ответственности."


def _report(contract_pdf, findings: list[ReportFinding]) -> ReportData:
    doc = ReportDocument(
        id=uuid.uuid4(), file_name="Проект контракта.pdf", relative_path="Проект контракта.pdf", status="COMPLETED",
        total_pages=2, is_scanned=False, law_type="44-FZ", risk_score=37, light="RED",
        preview_path=str(contract_pdf), error_message=None, findings=findings,
    )
    return ReportData(
        analysis_id=uuid.uuid4(), title="Проект контракта", original_filename="Проект контракта.pdf",
        created_at=datetime.now(), generated_at=datetime.now(), author="Автор", company="ООО Поставщик",
        rules_checked=2, documents=[doc], rules=[_rule("r1")],
    )


def _finding(number, severity, title, comment) -> ReportFinding:
    return ReportFinding(number=number, severity=severity, category="Обеспечение", title=title, short_description="Суть",
                         page_number=1 if number else None, clause="3.1" if number else None, exact_quote=None,
                         comment=comment, counter_proposal="Новая редакция", legal_reference="ст. 96 44-ФЗ",
                         review_status="NEW", reviewer_comment=None, quote_verified=True, source="LLM", highlights=[])


def test_detailed_report_hides_passed_check_that_contradicts_an_issue(contract_pdf, tmp_path):
    data = _report(contract_pdf, [
        _finding(1, "RED", "Завышенное обеспечение", "Обеспечение 30% выше обычного"),
        _finding(None, "GREEN", "Завышенное обеспечение", "Размер обеспечения в пределах нормы"),
        _finding(None, "GREEN", "Срок оплаты", "Срок оплаты 7 рабочих дней"),
    ])
    docx = DocxDocument(build_detailed(data, tmp_path / "detailed.docx"))
    text = "\n".join(p.text for p in docx.paragraphs)
    assert "Размер обеспечения в пределах нормы" not in text
    assert "Срок оплаты 7 рабочих дней" in text
    assert text.rstrip().endswith(DISCLAIMER)
