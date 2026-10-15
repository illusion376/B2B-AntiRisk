import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    finding_id: uuid.UUID | None = None
    mode: Literal["question", "report", "protocol"] = "question"

    @field_validator("message")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Введите вопрос")
        return value.strip()


class ChatSource(BaseModel):
    id: str
    label: str
    page: int | None = None
    finding_id: uuid.UUID | None = None
    quote: str = ""


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    finding_id: uuid.UUID | None
    sources: list[ChatSource]
    draft_title: str | None
    draft_content: str | None
    created_at: datetime


class ChatHistory(BaseModel):
    available: bool
    unavailable_reason: str | None
    messages: list[ChatMessageOut]


class ChatTurn(BaseModel):
    messages: list[ChatMessageOut]


class AssistantReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str = Field(min_length=1, max_length=16000)
    source_ids: list[str] = Field(max_length=12)
    draft_title: str | None = Field(max_length=255)
    draft_content: str | None = Field(max_length=30000)

    @field_validator("answer")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Пустой ответ")
        return value.strip()

    @field_validator("answer", "draft_title", "draft_content")
    @classmethod
    def valid_document_text(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("Недопустимые управляющие символы")
        return value
