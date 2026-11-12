"""Тесты песочницы проверки правил (Task 2: Rule Sandbox)."""
import math
import os
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.api import rules
from app.api.rules import _model_fields, _test_guidance, _run_rule
from app.config import settings
from app.models import Document, RiskRule
from app.schemas import RulePreviewRequest, RuleTestRequest
from app.services.retrieval import hybrid_search, vector_literal


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

    verdict, guidance = _test_guidance(has_risk=False, has_chunks=True)
    assert verdict == "NOT_FOUND"
    assert any("недостаточно данных" in tip for tip in guidance)

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
                doc.status = "ANALYZING"
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


@pytest.mark.parametrize("mode", ["keyword", "llm"])
def test_run_rule_without_relevant_chunks_skips_evaluation(monkeypatch, mode):
    document = Document(id=uuid.uuid4(), file_name="contract.pdf", status="COMPLETED")
    rule = RiskRule(id="draft", title="Телепортация в договоре",
                    semantic_query="Телепортация в договоре. Перемещение на Марс.",
                    query_embedding=[1.0, 0.0])
    db = Mock()
    db.get.return_value = document
    search = Mock(return_value=[])
    heuristic = Mock()
    llm = AsyncMock()
    monkeypatch.setattr(rules, "analysis_mode_or_422", lambda: mode)
    monkeypatch.setattr(rules, "ensure_rule_embeddings", lambda *_: None)
    monkeypatch.setattr(rules, "hybrid_search", search)
    monkeypatch.setattr(rules, "evaluate_heuristic", heuristic)
    monkeypatch.setattr(rules, "evaluate_with_llm", llm)

    result = _run_rule(db, rule, document_id=document.id)

    assert result.verdict == "NOT_FOUND"
    assert result.findings == result.fragments == []
    assert result.document_id == document.id
    assert any("Уточните название или описание" in item for item in result.guidance)
    search.assert_called_once_with(
        db, document.id, rule.semantic_query, [1.0, 0.0], settings.retrieval_top_k,
        max_distance=min(settings.retrieval_max_distance, rules._RULE_TEST_MAX_VECTOR_DISTANCE),
        rule_test_title=rule.title,
    )
    db.execute.assert_not_called()
    heuristic.assert_not_called()
    llm.assert_not_called()


def test_rule_test_retrieval_filters_weak_matches_before_top_k():
    url = os.getenv("B2B_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Для теста поиска нужен PostgreSQL с pgvector (B2B_TEST_POSTGRES_URL)")
    engine = create_engine(url)
    document_id, paraphrase_id = uuid.uuid4(), uuid.uuid4()
    chunks = [
        (document_id, "Условия договора определяют порядок оплаты оборудования.", 0.46),
        (document_id, "Цена услуг указана в приложении. Заказчик принимает оборудование.", 0.44),
        (document_id, "4.2. Срок оплаты составляет тридцать календарных дней.", 0.1),
        (paraphrase_id, "Заказчик перечисляет денежные средства после приёмки.", 0.85),
    ]
    try:
        with engine.begin() as db:
            db.execute(text("""
                CREATE TEMP TABLE document_chunks (
                    id uuid, document_id uuid, chunk_index integer, page_number integer, page_end integer,
                    clause_title text, content text, embedding vector(2),
                    tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED
                ) ON COMMIT DROP
            """))
            db.execute(text("""
                INSERT INTO document_chunks
                VALUES (:id, :document, :idx, :page, :page, NULL, :content, CAST(:embedding AS vector), DEFAULT)
            """), [
                dict(id=uuid.uuid4(), document=doc_id, idx=i, page=i + 1, content=content,
                     embedding=vector_literal([similarity, math.sqrt(1 - similarity ** 2)]))
                for i, (doc_id, content, similarity) in enumerate(chunks)
            ])

            title = "Телепортация в договоре"
            query = title + ". Перемещение на Марс."
            options = {"max_distance": rules._RULE_TEST_MAX_VECTOR_DISTANCE}
            assert [c.page_number for c in hybrid_search(db, document_id, query, [1, 0], 4, max_distance=0.58)] == [1, 2]
            assert hybrid_search(db, document_id, query, [1, 0], 1, rule_test_title=title, **options) == []

            title = "Срок оплаты"
            query = title + ". Уточните требования к предельному периоду погашения обязательства."
            assert [c.page_number for c in hybrid_search(
                db, document_id, query, [1, 0], 1, rule_test_title=title, **options,
            )] == [3]

            paraphrase = hybrid_search(db, paraphrase_id, query, [1, 0], 1, rule_test_title=title, **options)
            assert [c.page_number for c in paraphrase] == [4]
            assert not paraphrase[0].fts_hit
    finally:
        engine.dispose()
