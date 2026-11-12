"""Настраиваемые правила проверки (CheckRule во фронтенде): добавляются и меняются без изменения кода.

Во фронтенде у правила есть только название, описание, категория и степень риска. Поисковый запрос
и задание для ИИ при их отсутствии строятся из названия и описания.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import fields

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_document_or_404
from app.config import settings
from app.db import get_db
from app.models import Document, DocumentPage, RiskFinding, RiskRule, User
from app.schemas import (
    RuleCreate,
    RuleOut,
    RulePreviewRequest,
    RuleTestFinding,
    RuleTestFragment,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
)
from app.services.analysis_modes import analysis_mode_or_422
from app.services.analyzer import RuleContext, evaluate_heuristic, evaluate_with_llm
from app.services.audit import log_action
from app.services.pipeline import ensure_rule_embeddings
from app.services.retrieval import RetrievedChunk, hybrid_search
from app.vocab import SEVERITY_FROM_API, SEVERITY_TO_API

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rules", tags=["Правила проверки"])
_RULE_TEST_MAX_VECTOR_DISTANCE = 0.40

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
    data = body.model_dump(exclude={"id", "severity", "enabled", "document_id", "custom_text"})
    data["severity"] = SEVERITY_FROM_API[body.severity]
    data["is_active"] = body.enabled
    data["semantic_query"] = data.get("semantic_query") or default_query(body.title, body.description)
    data["llm_prompt"] = data.get("llm_prompt") or default_prompt(body.title, body.description)
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

    if auto_query and "semantic_query" not in changes:
        rule.semantic_query = default_query(rule.title, rule.description)
    if auto_prompt and "llm_prompt" not in changes:
        rule.llm_prompt = default_prompt(rule.title, rule.description)
    if rule.semantic_query != old_query:
        rule.query_embedding = None
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

    db.execute(delete(RiskFinding).where(RiskFinding.rule_id == rule_id))
    db.delete(rule)
    log_action(db, user.id, "RULE_DELETED", "rule", None, {"rule_id": rule_id, "title": rule.title})
    db.commit()

def _test_guidance(*, has_risk: bool, has_chunks: bool, has_green: bool = False) -> tuple[str, list[str]]:
    if has_risk:
        return "RISK", ["Правило успешно выявило потенциальный риск в проверенном тексте."]
    if not has_chunks:
        return "NOT_FOUND", [
            "В документе не найдены фрагменты, соответствующие поисковому запросу правила.",
            "Уточните название или описание правила: добавьте ключевые слова из условия договора "
            "(например, неустойка, односторонний отказ, срок оплаты).",
        ]
    if has_green:
        return "OK", [
            "В отобранных фрагментах система не зафиксировала нарушений по этому правилу.",
            "Совет: если пункт документа кажется вам рискованным, уточните в описании точный критерий нарушения "
            "(например: «срок возврата превышает 5 рабочих дней» вместо общего «проверить срок возврата»).",
        ]
    return "NOT_FOUND", [
        "В найденных фрагментах недостаточно данных для вывода по правилу.",
        "Уточните описание правила или проверьте найденные фрагменты вручную.",
    ]

def _run_rule(
    db: Session,
    rule: RiskRule,
    document_id: uuid.UUID | None = None,
    custom_text: str | None = None,
) -> RuleTestResult:
    mode = analysis_mode_or_422()
    start_time = time.monotonic()

    raw_text = (custom_text or "").strip()
    if not document_id and not raw_text:
        raise HTTPException(422, "Укажите документ для проверки или введите фрагмент текста")

    doc_id: uuid.UUID | None = None
    doc_file_name: str | None = None

    if raw_text and not document_id:
        chunks = [
            RetrievedChunk(
                id=uuid.uuid4(),
                chunk_index=0,
                page_number=1,
                page_end=1,
                clause_title="Пользовательский фрагмент",
                content=raw_text,
                score=1.0,
                fts_hit=True,
            )
        ]
        words = [[0.0, 0.0, 10.0, 10.0, w, 0] for w in raw_text.split()]
        pages = [{"page_number": 1, "words": words}]
        doc_name = "Фрагмент текста"
        law_type = rule.law_type if rule.law_type != "ALL" else None
        model = settings.llm_model.strip() if settings.llm_model else None
        sensitivity = "balanced"
    else:
        doc = db.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "Документ не найден")

        if doc.status in ("QUEUED", "CONVERTING", "OCR", "VECTORIZING", "ANALYZING"):
            raise HTTPException(
                409,
                f"Документ «{doc.file_name}» ещё обрабатывается ({doc.progress}%). Дождитесь завершения обработки.",
            )
        if doc.status != "COMPLETED":
            raise HTTPException(409, f"Документ «{doc.file_name}» не готов к проверке (статус: {doc.status}).")

        doc_id = doc.id
        doc_file_name = doc.file_name
        ensure_rule_embeddings(db, [rule])
        chunks = hybrid_search(
            db, doc.id, rule.semantic_query, list(rule.query_embedding), settings.retrieval_top_k,
            max_distance=min(settings.retrieval_max_distance, _RULE_TEST_MAX_VECTOR_DISTANCE),
            rule_test_title=rule.title,
        )
        pages = [
            {"page_number": n, "words": w}
            for n, w in db.execute(
                select(DocumentPage.page_number, DocumentPage.words)
                .where(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.page_number)
            )
        ] if chunks else []
        doc_name = doc.file_name
        law_type = doc.law_type
        model = doc.llm_model or (settings.llm_model.strip() if settings.llm_model else None)
        sensitivity = doc.analysis_sensitivity or "balanced"

    contexts = [RuleContext(rule, chunks)]
    drafts = []
    if chunks and mode == "llm":
        try:
            drafts = asyncio.run(evaluate_with_llm(contexts, pages, doc_name, law_type, sensitivity=sensitivity, model=model))
        except Exception as exc:
            log.warning("LLM evaluation failed in sandbox (%s), falling back to heuristic: %s", type(exc).__name__, exc)
            drafts = evaluate_heuristic(contexts, pages, sensitivity=sensitivity)
    elif chunks:
        drafts = evaluate_heuristic(contexts, pages, sensitivity=sensitivity)

    findings: list[RuleTestFinding] = []
    has_risk = False
    for d in drafts:
        api_severity = SEVERITY_TO_API.get(d.severity, "warning")
        if d.severity in ("RED", "YELLOW", "LOW", "UNKNOWN"):
            has_risk = True
        findings.append(
            RuleTestFinding(
                id=str(uuid.uuid4()),
                severity=api_severity,
                title=d.title,
                short_description=d.short_description,
                page=d.page_number,
                clause=d.clause,
                quote=d.exact_quote,
                comment=d.comment,
                counter_proposal=d.counter_proposal,
                confidence=d.confidence,
                quote_verified=d.quote_verified,
            )
        )

    fragments = [
        RuleTestFragment(
            page=c.page_number,
            clause_title=c.clause_title,
            content=c.content,
            score=round(c.score, 4),
        )
        for c in chunks
    ]

    execution_ms = round((time.monotonic() - start_time) * 1000)

    verdict, guidance = _test_guidance(
        has_risk=has_risk, has_chunks=bool(chunks), has_green=any(d.severity == "GREEN" for d in drafts),
    )

    return RuleTestResult(
        rule_id=rule.id,
        document_id=doc_id,
        document_name=doc_file_name,
        verdict=verdict,
        findings=findings,
        fragments=fragments,
        guidance=guidance,
        execution_ms=execution_ms,
    )

@router.post("/{rule_id}/test", response_model=RuleTestResult,
             summary="Проверить сохранённое правило на документе (результат не сохраняется)")
def test_rule(rule_id: str, body: RuleTestRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rule = _get(db, rule_id)
    doc_id = body.document_id
    if doc_id:
        doc = get_document_or_404(db, doc_id, user)
        doc_id = doc.id
    result = _run_rule(db, rule, document_id=doc_id, custom_text=body.custom_text)
    db.commit()
    return result

@router.post("/preview", response_model=RuleTestResult,
             summary="Проверить черновик правила на документе до сохранения")
def preview_rule(
    body: RulePreviewRequest,
    document_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc_id = body.document_id or document_id
    if doc_id:
        doc = get_document_or_404(db, doc_id, user)
        doc_id = doc.id
    draft = RiskRule(id=body.id or "draft", **_model_fields(body))
    return _run_rule(db, draft, document_id=doc_id, custom_text=body.custom_text)
