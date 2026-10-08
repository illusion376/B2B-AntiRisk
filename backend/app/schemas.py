"""Схемы API. Поля и значения совпадают с типами фронтенда (frontend/lib/types.ts), см. app/vocab.py."""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.vocab import ReviewStatus, RiskLevel, Severity

LawType = Literal["ALL", "44-FZ", "223-FZ"]
TrafficLight = Literal["critical", "warning", "ok"]
# Стадия обработки файла для интерфейса (как getProcessing() во фронтенде) + ошибки
Phase = Literal["uploaded", "queued", "processing", "ready", "failed", "unsupported"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Строки с обрезкой пробелов по краям; длины — как валидирует фронтенд
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    company_name: str | None
    role: str
    initials: str


class SeverityCounts(BaseModel):
    critical: int = 0
    warning: int = 0
    low: int = 0
    ok: int = 0
    unseen: int = 0  # замечания (не «ok») со статусом «Не просмотрено»


# ---------- Документы и файлы ----------

class DocumentOut(ORM):
    id: uuid.UUID
    analysis_id: uuid.UUID
    file_name: str
    relative_path: str | None  # путь внутри ZIP — для дерева содержимого архива
    file_type: str | None
    file_size: int | None
    status: str  # UPLOADED, QUEUED, CONVERTING, OCR, VECTORIZING, ANALYZING, COMPLETED, FAILED, UNSUPPORTED
    phase: Phase = "queued"
    label: str = ""  # «В очереди», «Распознавание текста», «Обработано»...
    progress: int
    total_pages: int
    is_scanned: bool
    ocr_pages: int
    ocr_confidence: float | None
    law_type: str | None
    risk_score: int | None
    traffic_light: TrafficLight | None = None
    counts: SeverityCounts = SeverityCounts()
    rules_checked: int = 0
    error_message: str | None
    processing_ms: int | None
    has_preview: bool = False
    created_at: datetime
    updated_at: datetime | None


class DocumentUpdate(BaseModel):
    file_name: FileName


class ProjectFileOut(BaseModel):
    """Загруженный файл проекта (ProjectFile во фронтенде). Для ZIP — documents содержит файлы архива."""
    id: uuid.UUID  # = id анализа
    name: str
    type: str  # pdf, txt, zip, docx...
    size: int | None
    added_at: datetime
    phase: Phase
    label: str
    progress: int
    status: str  # UPLOADED, QUEUED, OCR, VECTORIZING, ANALYZING, COMPLETED, FAILED
    error_message: str | None
    risk_score: int | None
    traffic_light: TrafficLight | None
    counts: SeverityCounts
    rules_checked: int
    documents: list[DocumentOut]


class ProjectCreate(BaseModel):
    title: Title
    description: LongText = ""


class ProjectUpdate(BaseModel):
    title: Title | None = None
    description: LongText | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    files: list[ProjectFileOut]
    processing_count: int  # файлов в обработке («В обработке: N»)
    counts: SeverityCounts  # замечания по всем файлам («Замечаний: N»)
    traffic_light: TrafficLight | None


class UploadError(BaseModel):
    name: str
    detail: str


class UploadResult(BaseModel):
    files: list[ProjectFileOut]
    errors: list[UploadError]


# ---------- Анализы (низкоуровневый API, без проектов) ----------

class AnalysisOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    original_filename: str
    file_type: str
    file_size: int | None
    law_type: str
    analysis_status: str
    progress: int
    risk_score: int | None
    traffic_light: TrafficLight | None = None
    rules_checked: int
    error_message: str | None
    documents_total: int = 0
    documents_supported: int = 0
    counts: SeverityCounts = SeverityCounts()
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None


class AnalysisDetail(AnalysisOut):
    documents: list[DocumentOut] = []


class AnalysisPage(BaseModel):
    items: list[AnalysisOut]
    total: int


# ---------- Замечания ----------

class Highlight(BaseModel):
    page: int
    rects: list[list[float]]  # [x0, y0, x1, y1] в PDF-пунктах, начало координат — левый верхний угол


class FindingOut(BaseModel):
    """Finding во фронтенде + доказательная база (цитата, норма, подсветка)."""
    id: uuid.UUID
    number: int | None  # номер в списке замечаний документа; у «ok» — None
    document_id: uuid.UUID
    rule_id: str | None
    title: str
    description: str  # краткая суть («Размер штрафа не ограничен суммой контракта»)
    severity: Severity
    category: str
    clause: str  # «6.2» — без «п.», как во фронтенде
    page: int | None
    quote: str
    recommendation: str
    comment: str  # подробное обоснование риска
    legal_reference: str | None
    highlights: list[Highlight]
    quote_verified: bool  # цитата найдена в тексте документа
    confidence: float | None
    source: str  # LLM, HEURISTIC, ERROR
    status: ReviewStatus
    reviewer_comment: str | None
    reviewed_at: datetime | None
    created_at: datetime


class FindingGroup(BaseModel):
    severity: Severity
    label: str
    count: int
    items: list[FindingOut]


class FindingsResponse(BaseModel):
    document_id: uuid.UUID | None
    total: int
    groups: list[FindingGroup]
    categories: list[str]  # для фильтра «Все категории»
    statuses: dict[str, int]  # прогресс просмотра: {"unseen": 5, "accepted": 2, "dismissed": 1}


class FindingUpdate(BaseModel):
    status: ReviewStatus | None = None
    reviewer_comment: str | None = Field(default=None, max_length=5000)


# ---------- Текст документа ----------

class OutlineClause(BaseModel):
    clause: str
    title: str
    page: int


class OutlineSection(BaseModel):
    title: str | None
    page: int
    clauses: list[OutlineClause] = []


class Paragraph(BaseModel):
    clause: str
    text: str
    finding_ids: list[uuid.UUID] = []


class Section(BaseModel):
    title: str
    paragraphs: list[Paragraph]


class PageContent(BaseModel):
    """Страница для HTML-просмотрщика фронтенда (getPageSections)."""
    page: int
    total_pages: int
    width: float
    height: float
    is_ocr: bool
    ocr_confidence: float | None
    sections: list[Section]


class SearchHit(BaseModel):
    page: int
    clause: str | None = None
    snippet: str
    highlights: list[Highlight]


class SearchResponse(BaseModel):
    query: str
    total: int
    hits: list[SearchHit]


# ---------- Правила ----------

class RuleFields(BaseModel):
    title: Title
    description: LongText = ""
    category: Category
    severity: RiskLevel
    enabled: bool = True
    # Расширенные настройки ИИ. Если не заданы — строятся из названия и описания
    law_type: LawType = "ALL"
    semantic_query: str | None = Field(default=None, description="Ключевые слова для поиска фрагментов")
    llm_prompt: str | None = Field(default=None, description="Что именно проверить ИИ")
    legal_reference: str | None = None
    sort_order: int = 100


class RuleCreate(RuleFields):
    id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,50}$",
                           description="Строковый ключ; если не задан — сгенерируется")


class RuleUpdate(BaseModel):
    title: Title | None = None
    description: LongText | None = None
    category: Category | None = None
    severity: RiskLevel | None = None
    enabled: bool | None = None
    law_type: LawType | None = None
    semantic_query: str | None = None
    llm_prompt: str | None = None
    legal_reference: str | None = None
    sort_order: int | None = None


class RuleOut(BaseModel):
    """CheckRule во фронтенде + расширенные настройки ИИ."""
    id: str
    title: str
    description: str
    category: str
    severity: RiskLevel
    enabled: bool
    law_type: str
    semantic_query: str
    llm_prompt: str
    legal_reference: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime | None


class RuleTestRequest(BaseModel):
    document_id: uuid.UUID


class RuleTestResult(BaseModel):
    rule_id: str
    findings: list[dict]
    fragments: list[dict]


class RerunRequest(BaseModel):
    rule_ids: list[str] | None = Field(default=None, description="Только эти правила; по умолчанию — все активные")


# ---------- Отчёты и история ----------

class ReportMode(BaseModel):
    id: str
    title: str
    description: str
    formats: list[str]


class HistoryEntry(BaseModel):
    """HistoryEntry во фронтенде (+ время в ISO и ссылка на объект)."""
    id: uuid.UUID
    action: str
    title: str
    detail: str
    time: datetime
    entity_type: str
    entity_id: uuid.UUID | None
