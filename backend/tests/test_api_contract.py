"""Контракт API с фронтендом: словарь, валидация, правила из интерфейса, история."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.history import describe
from app.api.rules import _model_fields, default_prompt, default_query
from app.schemas import ProjectCreate, RuleCreate
from app.vocab import REVIEW_FROM_API, SEVERITY_FROM_API, parse_filter, weaker


def test_vocabulary():
    assert parse_filter("critical, warning", SEVERITY_FROM_API, "severity") == ["RED", "YELLOW"]
    assert parse_filter("unseen,accepted", REVIEW_FROM_API, "status") == ["NEW", "CONFIRMED"]
    assert parse_filter(None, SEVERITY_FROM_API, "severity") is None
    with pytest.raises(HTTPException):
        parse_filter("RED", SEVERITY_FROM_API, "severity")
    assert weaker("RED", "LOW") == "LOW" and weaker("LOW", "YELLOW") == "LOW"


def test_project_validation():
    assert ProjectCreate(title="  Договор поставки ").title == "Договор поставки"
    with pytest.raises(ValidationError):
        ProjectCreate(title="   ")
    with pytest.raises(ValidationError):
        ProjectCreate(title="x" * 121)


def test_rule_from_frontend_form():
    """Фронтенд присылает только название, описание, категорию и степень риска."""
    body = RuleCreate(title="Срок оплаты", description="Оплата не позднее 7 рабочих дней", category="Оплата",
                      severity="low")
    fields = _model_fields(body)
    assert fields["severity"] == "LOW" and fields["is_active"] is True
    assert fields["semantic_query"] == default_query(body.title, body.description)
    assert fields["llm_prompt"] == default_prompt(body.title, body.description)
    assert "Срок оплаты" in fields["llm_prompt"]
    with pytest.raises(ValidationError):
        RuleCreate(title="x", category="y", severity="RED")  # только critical / warning / low


def test_history_wording():
    title, detail = describe("ANALYSIS_COMPLETED", {"file": "Проект контракта.pdf", "rules": 20, "critical": 3,
                                                    "warning": 5, "low": 0})
    assert title == "Проверка документа завершена"
    assert detail == "Проект контракта.pdf · 20 правил · 3 критических замечания · 5 требуют внимания"
    assert describe("RULE_TOGGLED", {"title": "Субподряд", "enabled": False}) == ("Правило отключено", "Субподряд")
