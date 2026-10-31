import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.analysis_modes import AnalysisModeError, capabilities, default_analysis_mode, resolve_analysis_mode


@pytest.fixture(autouse=True)
def proxy_config(monkeypatch):
    monkeypatch.setattr(settings, "analysis_engine", "auto")
    monkeypatch.setattr(settings, "heuristic_engine", "keyword")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.proxyapi.ru/v1")
    monkeypatch.setattr(settings, "llm_model", "openai/gpt-4.1-mini")
    monkeypatch.setattr(settings, "llm_api_key", "test-proxy-key")


def test_api_capabilities_expose_only_remote_llm_and_keywords():
    response = TestClient(app).get("/api/analysis-modes")
    assert response.status_code == 200
    data = response.json()
    assert data["default_mode"] == "llm"
    assert [mode["id"] for mode in data["modes"]] == ["llm", "keyword"]
    assert all(mode["available"] for mode in data["modes"])
    assert data["configured_model"] == "openai/gpt-4.1-mini"
    assert "test-proxy-key" not in response.text
    assert "https://" not in response.text


@pytest.mark.parametrize("field,value", [
    ("llm_api_key", None), ("llm_api_key", " "),
    ("llm_model", ""), ("llm_base_url", " "),
])
def test_missing_config_disables_llm_and_never_replaces_explicit_selection(monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    assert default_analysis_mode() == "keyword"
    assert capabilities().model_dump()["modes"][0]["available"] is False
    assert resolve_analysis_mode() == "keyword"
    with pytest.raises(AnalysisModeError, match="LLM недоступна"):
        resolve_analysis_mode("llm")


def test_explicit_default_is_not_replaced_when_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "analysis_engine", "llm")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert capabilities().model_dump()["default_mode"] == "llm"
    with pytest.raises(AnalysisModeError):
        resolve_analysis_mode()
    assert resolve_analysis_mode("keyword") == "keyword"


@pytest.mark.parametrize("field", ["analysis_engine", "heuristic_engine"])
def test_legacy_nli_configuration_is_visible_but_cannot_load_a_model(monkeypatch, field):
    monkeypatch.setattr(settings, field, "nli")
    monkeypatch.setattr(settings, "llm_api_key", "")
    modes = capabilities().model_dump()
    assert modes["default_mode"] == "nli"
    assert next(mode for mode in modes["modes"] if mode["id"] == "nli")["available"] is False
    with pytest.raises(AnalysisModeError, match="NLI-модель отключена"):
        resolve_analysis_mode()
    assert resolve_analysis_mode("keyword") == "keyword"


def test_disabled_nli_has_a_structured_422_error():
    from app.services.analysis_modes import analysis_mode_or_422
    with pytest.raises(HTTPException) as caught:
        analysis_mode_or_422("nli")
    assert caught.value.status_code == 422
    assert caught.value.detail["analysis_mode"] == "nli"
    assert caught.value.detail["code"] == "analysis_mode_unavailable"


def test_invalid_mode_is_not_interpreted_as_default():
    with pytest.raises(AnalysisModeError, match="Неизвестный"):
        resolve_analysis_mode("")


@pytest.mark.parametrize("engine,key", [("nli", "test-key"), ("llm", "")])
def test_rule_preview_cannot_bypass_mode_availability(monkeypatch, engine, key):
    import uuid
    from unittest.mock import MagicMock
    from app.api.rules import _run_rule
    from app.models import RiskRule

    monkeypatch.setattr(settings, "analysis_engine", engine)
    monkeypatch.setattr(settings, "llm_api_key", key)
    db = MagicMock()
    with pytest.raises(HTTPException) as caught:
        _run_rule(db, RiskRule(id="test-rule"), uuid.uuid4())
    assert caught.value.status_code == 422
    assert caught.value.detail["analysis_mode"] == engine
    db.execute.assert_not_called()
    db.commit.assert_not_called()
