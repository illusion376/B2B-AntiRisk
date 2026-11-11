"""Тесты песочницы проверки правил (Task 2: Rule Sandbox)."""
import uuid
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.rules import _model_fields, _test_guidance, _run_rule
from app.models import Document, RiskRule
from app.schemas import RulePreviewRequest, RuleTestRequest, RuleTestResult


def test_rule_test_request_validation():
    req = RuleTestRequest(document_id=uuid.uuid4(), custom_text="Тестовый текст")
    assert req.document_id is not None
    assert req.custom_text == "Тестовый текст"

    req_none = RuleTestRequest()
    assert req_none.document_id is None
    assert req_none.custom_text is None


def test_rule_preview_request_excludes_sandbox_fields():
    doc_id = uuid.uuid4()
    body = RulePreviewRequest(
        title="Срок оплаты по 44-ФЗ",
        description="Проверка соблюдения 7 рабочих дней на оплату",
        category="Оплата",
        severity="critical",
        document_id=doc_id,
        custom_text="Заказчик производит оплату в течение 30 дней",
    )
    fields = _model_fields(body)
    assert "document_id" not in fields
    assert "custom_text" not in fields
    assert fields["severity"] == "RED"
    assert fields["title"] == "Срок оплаты по 44-ФЗ"
    assert "Срок оплаты" in fields["llm_prompt"]


def test_rule_test_guidance():
    # Нет фрагментов
    verdict, guidance_no_chunks = _test_guidance(has_risk=False, has_chunks=False)
    assert verdict == "NOT_FOUND"
    assert any("не найдены фрагменты" in tip for tip in guidance_no_chunks)
    assert any("ключевые слова" in tip.lower() for tip in guidance_no_chunks)

    # Фрагменты найдены, нарушений нет (OK)
    verdict_ok, guidance_ok = _test_guidance(has_risk=False, has_chunks=True, has_green=True)
    assert verdict_ok == "OK"
    assert any("не зафиксировала нарушений" in tip for tip in guidance_ok)

    # Риск найден
    verdict_risk, guidance_risk = _test_guidance(has_risk=True, has_chunks=True)
    assert verdict_risk == "RISK"
    assert any("успешно выявило потенциальный риск" in tip for tip in guidance_risk)


def test_run_rule_unready_document_raises_409():
    rule = RiskRule(
        id="test_rule",
        law_type="44-FZ",
        category="Оплата",
        severity="YELLOW",
        title="Тест",
        description="Тест",
        semantic_query="тест",
        llm_prompt="тест",
    )

    class DummySession:
        def get(self, model, ident):
            if model == Document:
                doc = Document(id=ident, analysis_id=uuid.uuid4(), file_name="doc.pdf", file_type="pdf", file_size=100)
                doc.status = "PROCESSING"
                return doc
            return None

    with pytest.raises(HTTPException) as exc_info:
        _run_rule(DummySession(), rule, document_id=uuid.uuid4())
    assert exc_info.value.status_code == 409
    assert "ещё обрабатывается" in exc_info.value.detail


def test_run_rule_missing_document_raises_404():
    rule = RiskRule(
        id="test_rule",
        law_type="44-FZ",
        category="Оплата",
        severity="YELLOW",
        title="Тест",
        description="Тест",
        semantic_query="тест",
        llm_prompt="тест",
    )

    class DummySession:
        def get(self, model, ident):
            return None

    with pytest.raises(HTTPException) as exc_info:
        _run_rule(DummySession(), rule, document_id=uuid.uuid4())
    assert exc_info.value.status_code == 404
