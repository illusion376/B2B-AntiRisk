import re
from pathlib import Path

import pytest
from app.models import RiskRule


def _load_migration_rules() -> list[dict]:
    migration_path = Path(__file__).resolve().parents[2] / "database" / "migrations" / "005_tz_and_qualification_rules.sql"
    assert migration_path.exists(), "Файл миграции 005_tz_and_qualification_rules.sql должен существовать"
    sql = migration_path.read_text(encoding="utf-8")

    # Регулярка для извлечения кортежей значений из INSERT INTO risk_rules
    # ('id', 'law', 'cat', 'sev', 'title', 'desc', 'query', 'prompt', 'legal', sort)
    pattern = re.compile(
        r"\(\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*(\d+)\s*\)",
        re.MULTILINE | re.DOTALL,
    )
    matches = pattern.findall(sql)
    rules = []
    for match in matches:
        rules.append({
            "id": match[0],
            "law_type": match[1],
            "category": match[2],
            "severity": match[3],
            "title": match[4],
            "description": match[5],
            "semantic_query": match[6],
            "llm_prompt": match[7],
            "legal_reference": match[8],
            "sort_order": int(match[9]),
        })
    return rules


def test_migration_005_rules_exist():
    rules = _load_migration_rules()
    rule_ids = {r["id"] for r in rules}

    expected_ids = {
        "brand_without_equivalent",
        "experience_restricted_44_223",
        "excessive_application_demands",
    }
    assert expected_ids.issubset(rule_ids), f"Не все ожидаемые правила найдены в миграции: {expected_ids - rule_ids}"


def test_migration_005_rules_structure():
    rules = _load_migration_rules()
    for rule in rules:
        # Проверка создания ORM модели RiskRule
        orm_rule = RiskRule(**rule)
        assert orm_rule.id in ("brand_without_equivalent", "experience_restricted_44_223", "excessive_application_demands")
        assert orm_rule.law_type in ("ALL", "44-FZ", "223-FZ")
        assert orm_rule.severity in ("RED", "YELLOW", "LOW")
        assert len(orm_rule.semantic_query.split()) >= 5, "Семантический запрос должен содержать минимум 5 ключевых слов"
        assert len(orm_rule.llm_prompt) >= 50, "Промпт правила должен быть подробным"
        assert orm_rule.legal_reference is not None and len(orm_rule.legal_reference) > 0


def test_brand_without_equivalent_rule():
    rules = {r["id"]: r for r in _load_migration_rules()}
    rule = rules["brand_without_equivalent"]

    assert rule["severity"] == "RED"
    assert rule["category"] == "Техническое задание"
    assert "33 44-ФЗ" in rule["legal_reference"]
    assert "эквивалент" in rule["semantic_query"]


def test_experience_restricted_rule():
    rules = {r["id"]: r for r in _load_migration_rules()}
    rule = rules["experience_restricted_44_223"]

    assert rule["severity"] == "RED"
    assert rule["category"] == "Квалификационные требования"
    assert "31 44-ФЗ" in rule["legal_reference"]
    assert "коммерческий" in rule["semantic_query"]


def test_excessive_application_demands_rule():
    rules = {r["id"]: r for r in _load_migration_rules()}
    rule = rules["excessive_application_demands"]

    assert rule["severity"] == "YELLOW"
    assert rule["category"] == "Требования к составу заявки"
    assert "43 44-ФЗ" in rule["legal_reference"]
    assert "сертификат" in rule["semantic_query"]
