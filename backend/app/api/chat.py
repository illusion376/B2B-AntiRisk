import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO

import httpx
from docx import Document as WordDocument
from docx.shared import Pt
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_document_or_404
from app.api.documents import content_disposition
from app.chat_schemas import ChatHistory, ChatMessageOut, ChatRequest, ChatTurn
from app.config import settings
from app.db import get_db
from app.models import Document, DocumentChatMessage, User
from app.services import document_chat
from app.services.llm import LLMError, failure_code

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents/{document_id}/chat", tags=["ИИ-помощник"])

def _ready(db: Session, document_id: uuid.UUID, user: User) -> Document:
    document = get_document_or_404(db, document_id, user)
    if document.status != "COMPLETED":
        raise HTTPException(409, "Помощник доступен после завершения анализа документа")
    return document

def _history(db: Session, document: Document, user: User) -> list[DocumentChatMessage]:
    messages = list(db.scalars(select(DocumentChatMessage).where(
        DocumentChatMessage.document_id == document.id,
        DocumentChatMessage.user_id == user.id,
        DocumentChatMessage.context_version == document_chat.context_version(document),
    ).order_by(DocumentChatMessage.created_at.desc(), DocumentChatMessage.id.desc()).limit(80)))
    return list(reversed(messages))

@router.get("", response_model=ChatHistory)
def history(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    document = _ready(db, document_id, user)
    return ChatHistory(
        available=settings.llm_enabled,
        unavailable_reason=None if settings.llm_enabled else "ИИ-помощник не настроен. Обратитесь к администратору.",
        messages=[ChatMessageOut.model_validate(m) for m in _history(db, document, user)],
    )

@router.post("", response_model=ChatTurn)
async def send(document_id: uuid.UUID, body: ChatRequest, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    document = _ready(db, document_id, user)
    if not settings.llm_enabled:
        raise HTTPException(503, "ИИ-помощник не настроен. Обратитесь к администратору.")

    lock_key = int.from_bytes(hashlib.blake2b(f"chat:{document.id}:{user.id}".encode(), digest_size=8).digest(),
                              "big", signed=True)
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key}):
        raise HTTPException(409, "Помощник уже готовит ответ для этого документа. Дождитесь завершения.")
    version = document_chat.context_version(document)
    findings = document_chat.visible_results(db, document)
    selected = next((f for f in findings if f.id == body.finding_id), None)
    if body.finding_id and selected is None:
        raise HTTPException(404, "Замечание не найдено в текущем документе или его правило отключено")
    findings_version = document_chat.results_version(findings)
    messages = _history(db, document, user)

    previous_question = next((m.content for m in reversed(messages) if m.role == "user"), "")
    context = document_chat.build_context(db, document, user, findings, selected,
                                         body.message + " " + previous_question)
    started_at = datetime.now(timezone.utc)
    try:

        async with asyncio.timeout(170):
            reply, sources = await document_chat.answer(context, body, messages)
    except (TimeoutError, httpx.TimeoutException) as exc:
        db.rollback()
        raise HTTPException(504, "Помощник не успел ответить. Попробуйте ещё раз.") from exc
    except (LLMError, httpx.HTTPError, ValidationError) as exc:
        db.rollback()
        log.warning("Document assistant failed: %s", failure_code(exc))
        raise HTTPException(502, "Не удалось получить корректный ответ помощника. Попробуйте ещё раз.") from exc

    db.expire_all()
    document = _ready(db, document_id, user)
    if version != document_chat.context_version(document) or findings_version != document_chat.results_version(
        document_chat.visible_results(db, document)
    ):
        raise HTTPException(409, "Результаты анализа изменились. Обновите страницу и повторите вопрос.")
    question = DocumentChatMessage(
        document_id=document.id, user_id=user.id, context_version=version, role="user",
        content=body.message, finding_id=body.finding_id,
        sources=[context.sources[f"finding-{selected.id}"].model_dump(mode="json")] if selected else [],
        created_at=started_at,
    )
    response = DocumentChatMessage(
        document_id=document.id, user_id=user.id, context_version=version, role="assistant",
        content=reply.answer, finding_id=body.finding_id, sources=sources,
        draft_title=reply.draft_title, draft_content=reply.draft_content, created_at=datetime.now(timezone.utc),
    )
    db.add_all([question, response])
    db.commit()
    return ChatTurn(messages=[ChatMessageOut.model_validate(m) for m in (question, response)])

@router.get("/{message_id}/draft", summary="Скачать подготовленный помощником черновик Word")
def download_draft(document_id: uuid.UUID, message_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    document = _ready(db, document_id, user)
    message = db.scalar(select(DocumentChatMessage).where(
        DocumentChatMessage.id == message_id, DocumentChatMessage.document_id == document.id,
        DocumentChatMessage.user_id == user.id, DocumentChatMessage.role == "assistant",
        DocumentChatMessage.context_version == document_chat.context_version(document),
    ))
    if message is None or not message.draft_content:
        raise HTTPException(404, "Черновик не найден для текущего анализа")
    report = WordDocument()
    report.core_properties.author = user.full_name
    report.styles["Normal"].font.name = "Calibri"
    report.styles["Normal"].font.size = Pt(11)
    report.add_heading(message.draft_title or "Черновик отчёта", 0)
    report.add_paragraph(f"Документ: {document.file_name}")
    report.add_paragraph(f"Подготовил: {user.full_name}")
    if user.company_name:
        report.add_paragraph(f"Компания: {user.company_name}")
    report.add_paragraph("Черновик ИИ-помощника на основе результатов анализа. Требует проверки перед использованием.")
    for paragraph in message.draft_content.splitlines():
        report.add_paragraph(paragraph)
    if message.sources:
        report.add_heading("Источники", level=1)
        for source in message.sources:
            report.add_paragraph(source["label"] + (f" · стр. {source['page']}" if source.get("page") else ""))
            if source.get("quote"):
                report.add_paragraph(source["quote"])
    buffer = BytesIO()
    report.save(buffer)
    return Response(buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": content_disposition("Черновик_ИИ.docx"),
                             "Cache-Control": "no-store"})
