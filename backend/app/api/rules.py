"""Настраиваемые правила проверки (CheckRule во фронтенде): добавляются и меняются без изменения кода.

Во фронтенде у правила есть только название, описание, категория и степень риска. Поисковый запрос
и задание для ИИ при их отсутствии строятся из названия и описания.
"""
import asyncio
import uuid
from dataclasses import fields

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_document_or_404
from app.config import settings
from app.db import get_db
from app.models import DocumentPage, RiskFinding, RiskRule, User
from app.schemas import RuleCreate, RuleOut, RuleTestRequest, RuleTestResult, RuleUpdate
from app.services.analyzer import RuleContext, evaluate_heuristic, evaluate_nli, evaluate_with_llm
from app.services.audit import log_action
from app.services.pipeline import ensure_rule_embeddings
from app.services.retrieval import hybrid_search
from app.vocab import SEVERITY_FROM_API, SEVERITY_TO_API

router = APIRouter(prefix="/api/rules", tags=["Правила проверки"])


def default_query(title: str, description: str) -> str:
    return f"{title}. {description}".strip(" .")


def default_prompt(title: str, description: str) -> str:
    text = f"Проверь условие «{title}»."
    if description:
        text += f" {description.rstrip('.')}."
    return text + " Риском является условие, которое ухудшает положение поставщика или нарушает 44-ФЗ / 223-ФЗ."


def rule_out(rule: RiskRule) -> RuleOut:
    return RuleOut(
        id=rule.id, title=rule.title, description=rule.description, category=rule.category,
        severity=SEVERITY_TO_API.get(rule.severity, "warning"), enabled=rule.is_active,
        law_type=rule.law_type, semantic_query=rule.semantic_query, llm_prompt=rule.llm_prompt,
        legal_reference=rule.legal_reference, sort_order=rule.sort_order,
        created_at=rule.created_at, updated_at=rule.updated_at,
    )


def _model_fields(body: RuleCreate) -> dict:
    data = body.model_dump(exclude={"id", "severity", "enabled"})
    data["severity"] = SEVERITY_FROM_API[body.severity]
    data["is_active"] = body.enabled
    data["semantic_query"] = data["semantic_query"] or default_query(body.title, body.description)
    data["llm_prompt"] = data["llm_prompt"] or default_prompt(body.title, body.description)
    return data


def _get(db: Session, rule_id: str) -> RiskRule:
    rule = db.get(RiskRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Правило не найдено")
    return rule


def _require_editor(user: User) -> None:
    if user.role == "AUDITOR":
        raise HTTPException(403, "Недостаточно прав для изменения правил")


@router.get("", response_model=list[RuleOut], summary="Список правил")
def list_rules(
    enabled: bool | None = Query(None),
    law_type: str | None = Query(None, description="44-FZ / 223-FZ / ALL"),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    query = select(RiskRule).order_by(RiskRule.sort_order, RiskRule.created_at, RiskRule.id)
    if enabled is not None:
        query = query.where(RiskRule.is_active.is_(enabled))
    if law_type:
        query = query.where(RiskRule.law_type.in_(["ALL", law_type]) if law_type != "ALL" else RiskRule.law_type == "ALL")
    if category:
        query = query.where(RiskRule.category == category)
    return [rule_out(r) for r in db.scalars(query)]


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return rule_out(_get(db, rule_id))


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED, summary="Добавить правило")
def create_rule(body: RuleCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _require_editor(user)
    rule_id = body.id or f"custom_{uuid.uuid4().hex[:10]}"
    if db.get(RiskRule, rule_id):
        raise HTTPException(409, f"Правило с id «{rule_id}» уже существует")
    rule = RiskRule(id=rule_id, **_model_fields(body))
    db.add(rule)
    log_action(db, user.id, "RULE_CREATED", "rule", None, {"rule_id": rule_id, "title": rule.title})
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.patch("/{rule_id}", response_model=RuleOut, summary="Изменить правило (в т. ч. включить/выключить)")
def update_rule(rule_id: str, body: RuleUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _require_editor(user)
    rule = _get(db, rule_id)
    changes = body.model_dump(exclude_unset=True)
    old_query = rule.semantic_query
    auto_query = rule.semantic_query == default_query(rule.title, rule.description)
    auto_prompt = rule.llm_prompt == default_prompt(rule.title, rule.description)

    if changes.get("severity"):
        rule.severity = SEVERITY_FROM_API[changes.pop("severity")]
    if "enabled" in changes:
        enabled = changes.pop("enabled")
        if enabled is not None:
            rule.is_active = enabled
    for key, value in changes.items():
        if value is not None or key in ("legal_reference",):
            setattr(rule, key, value)
    # Автоматически построенные запрос и задание следуют за названием и описанием
    if auto_query and "semantic_query" not in changes:
        rule.semantic_query = default_query(rule.title, rule.description)
    if auto_prompt and "llm_prompt" not in changes:
        rule.llm_prompt = default_prompt(rule.title, rule.description)
    if rule.semantic_query != old_query:
        rule.query_embedding = None  # пересчитается при следующей проверке
        rule.embedding_model = None
    action = "RULE_TOGGLED" if set(body.model_dump(exclude_unset=True)) == {"enabled"} else "RULE_UPDATED"
    log_action(db, user.id, action, "rule", None, {"rule_id": rule_id, "title": rule.title, "enabled": rule.is_active})
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить правило и его замечания")
def delete_rule(rule_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _require_editor(user)
    rule = _get(db, rule_id)
    # Во фронтенде замечания удалённого правила перестают отображаться
    db.execute(delete(RiskFinding).where(RiskFinding.rule_id == rule_id))
    db.delete(rule)
    log_action(db, user.id, "RULE_DELETED", "rule", None, {"rule_id": rule_id, "title": rule.title})
    db.commit()


def _run_rule(db: Session, rule: RiskRule, document_id: uuid.UUID) -> RuleTestResult:
    ensure_rule_embeddings(db, [rule])
    chunks = hybrid_search(db, document_id, rule.semantic_query, list(rule.query_embedding), settings.retrieval_top_k)
    pages = [
        {"page_number": n, "words": w}
        for n, w in db.execute(select(DocumentPage.page_number, DocumentPage.words)
                               .where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number))
    ]
    contexts = [RuleContext(rule, chunks)]
    doc_name = str(document_id)
    if settings.llm_enabled:
        drafts = asyncio.run(evaluate_with_llm(contexts, pages, doc_name, None))
    elif settings.heuristic_engine == "nli":
        drafts = evaluate_nli(contexts, pages)
    else:
        drafts = evaluate_heuristic(contexts, pages)
    findings = []
    for d in drafts:
        item = {f.name: getattr(d, f.name) for f in fields(d) if f.name != "rule"}
        item["severity"] = SEVERITY_TO_API.get(d.severity, "warning")
        findings.append(item)
    fragments = [
        {"page": c.page_number, "clause_title": c.clause_title, "content": c.content, "score": round(c.score, 4)}
        for c in chunks
    ]
    return RuleTestResult(rule_id=rule.id, findings=findings, fragments=fragments)


@router.post("/{rule_id}/test", response_model=RuleTestResult,
             summary="Проверить сохранённое правило на документе (результат не сохраняется)")
def test_rule(rule_id: str, body: RuleTestRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = get_document_or_404(db, body.document_id, user)
    if doc.status != "COMPLETED":
        raise HTTPException(409, "Документ ещё не обработан")
    result = _run_rule(db, _get(db, rule_id), doc.id)
    db.commit()  # кэш эмбеддинга правила
    return result


@router.post("/preview", response_model=RuleTestResult,
             summary="Проверить черновик правила на документе до сохранения")
def preview_rule(body: RuleCreate, document_id: uuid.UUID = Query(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    doc = get_document_or_404(db, document_id, user)
    if doc.status != "COMPLETED":
        raise HTTPException(409, "Документ ещё не обработан")
    draft = RiskRule(id=body.id or "draft", **_model_fields(body))
    return _run_rule(db, draft, doc.id)
