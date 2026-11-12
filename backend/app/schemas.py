"""Схемы API. Поля и значения совпадают с типами фронтенда (frontend/lib/types.ts), см. app/vocab.py."""
import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.vocab import ReviewStatus, RiskLevel, Severity

LawType = Literal["ALL", "44-FZ", "223-FZ"]
TrafficLight = Literal["critical", "warning", "ok", "unknown"]
AnalysisMode = Literal["llm", "nli", "keyword"]
AnalysisSensitivity = Literal["strict", "balanced", "sensitive"]

Phase = Literal["uploaded", "queued", "processing", "ready", "failed", "unsupported"]

class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

class QualitySettings(BaseModel):
    """Личные нормативы для следующих полных проверок документов."""
    model_config = ConfigDict(extra="forbid")
    ocr_min_confidence: float = Field(ge=0, le=100, allow_inf_nan=False, strict=True)
    processing_sla_seconds: int | None = Field(ge=1, le=2_147_483, strict=True)

class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    company_name: str | None
    role: str
    initials: str
    quality_settings: QualitySettings

class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    quality_settings: QualitySettings | None = None

    @model_validator(mode="after")
    def validate_partial_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Укажите изменённые настройки или данные профиля")
        for name in ("full_name", "quality_settings"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"Поле {name} не может быть null")
        return self

class SeverityCounts(BaseModel):
    critical: int = 0
    warning: int = 0
    low: int = 0
    ok: int = 0
    unknown: int = 0
    unseen: int = 0

QualityStatus = Literal["ok", "low", "unknown", "native"]

class PageQualityIssue(BaseModel):
    page: int = Field(ge=1)
    status: Literal["low", "unknown"]
    confidence: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    reason: str
    warning: str

class PageQuality(BaseModel):
    status: QualityStatus = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    confidence_threshold: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    manual_review_required: bool = False
    warning: str | None = None
    reason: str | None = None

class DocumentQuality(BaseModel):
    """Качество извлечения текста, а не вероятность правильности юридических выводов."""
    status: QualityStatus = "unknown"
    confidence_threshold: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    confidence: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    total_pages: int = Field(default=0, ge=0)
    ocr_pages: int = Field(default=0, ge=0)
    native_pages: int = Field(default=0, ge=0)
    ocr_percent: float | None = Field(default=None, ge=0, le=100)
    native_percent: float | None = Field(default=None, ge=0, le=100)
    measured_ocr_pages: int = Field(default=0, ge=0)
    review_pages: list[PageQualityIssue] = Field(default_factory=list)
    manual_review_required: bool = False
    warning: str | None = None
    processing_ms: int | None = Field(default=None, ge=0)
    processing_kind: Literal["full", "reanalysis"] | None = None
    sla_ms: int | None = Field(default=None, gt=0)
    sla_status: Literal["within", "exceeded", "not_configured", "not_measured", "not_applicable"] = "not_measured"

class DocumentOut(ORM):
    id: uuid.UUID
    analysis_id: uuid.UUID
    file_name: str
    relative_path: str | None
    file_type: str | None
    file_size: int | None
    status: str
    analysis_mode: AnalysisMode | None = Field(default=None, description=(
        "Последний выбранный режим. При частичной или неудачной повторной проверке могут сохраняться "
        "предыдущие результаты; источник каждого замечания указан в source. NULL — старый запуск без записи режима."
    ))
    llm_model: str | None = Field(default=None, description="Модель, выбранная при последнем запуске проверки")
    phase: Phase = "queued"
    analysis_sensitivity: AnalysisSensitivity | None = None
    chat_revision: uuid.UUID | None = None
    label: str = ""
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
    quality: DocumentQuality = Field(default_factory=DocumentQuality)
    has_preview: bool = False
    created_at: datetime
    updated_at: datetime | None

class DocumentUpdate(BaseModel):
    file_name: FileName

class ProjectFileOut(BaseModel):
    """Загруженный файл проекта (ProjectFile во фронтенде). Для ZIP — documents содержит файлы архива."""
    id: uuid.UUID
    name: str
    type: str
    size: int | None
    added_at: datetime
    phase: Phase
    label: str
    progress: int
    status: str
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
    is_rule_test: bool = False
    created_at: datetime
    updated_at: datetime
    files: list[ProjectFileOut]
    processing_count: int
    counts: SeverityCounts
    traffic_light: TrafficLight | None

class UploadError(BaseModel):
    name: str
    detail: str

class UploadResult(BaseModel):
    files: list[ProjectFileOut]
    errors: list[UploadError]

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

class Highlight(BaseModel):
    page: int
    rects: list[list[float]]

class FindingOut(BaseModel):
    """Finding во фронтенде + доказательная база (цитата, норма, подсветка)."""
    id: uuid.UUID
    number: int | None
    document_id: uuid.UUID
    rule_id: str | None
    title: str
    description: str
    severity: Severity
    category: str
    clause: str
    page: int | None
    quote: str
    recommendation: str
    comment: str
    legal_reference: str | None
    highlights: list[Highlight]
    quote_verified: bool
    confidence: float | None
    source: str
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
    categories: list[str]
    statuses: dict[str, int]

class FindingUpdate(BaseModel):
    status: ReviewStatus | None = None
    reviewer_comment: str | None = Field(default=None, max_length=5000)

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
    quality: PageQuality = Field(default_factory=PageQuality)
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

class RuleFields(BaseModel):
    title: Title
    description: LongText = ""
    category: Category
    severity: RiskLevel
    enabled: bool = True

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

class RuleTestFinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: RiskLevel | Literal["critical", "warning", "low", "ok", "unknown"]
    title: str
    short_description: str | None = None
    page: int | None = None
    clause: str | None = None
    quote: str | None = None
    comment: str | None = None
    counter_proposal: str | None = None
    confidence: float | None = None
    quote_verified: bool = False

class RuleTestFragment(BaseModel):
    page: int
    clause_title: str | None = None
    content: str
    score: float

class RuleTestResult(BaseModel):
    rule_id: str
    document_id: uuid.UUID | None = None
    document_name: str | None = None
    verdict: str = "NOT_FOUND"
    findings: list[RuleTestFinding] = []
    fragments: list[RuleTestFragment] = []
    guidance: list[str] = []
    execution_ms: int | None = None

class RuleTestRequest(BaseModel):
    document_id: uuid.UUID | None = None
    custom_text: str | None = Field(default=None, max_length=15000)

class RulePreviewRequest(RuleCreate):
    document_id: uuid.UUID | None = None
    custom_text: str | None = Field(default=None, max_length=15000)

class StartRequest(BaseModel):
    analysis_mode: str | None = Field(default=None, description="llm, nli или keyword; по умолчанию — режим сервера")
    llm_model: str | None = Field(default=None, min_length=1, max_length=200, description="Идентификатор модели ProxyAPI")
    analysis_sensitivity: AnalysisSensitivity = Field(default="balanced", description="Чувствительность к потенциальным рискам")

class RerunRequest(StartRequest):
    rule_ids: list[str] | None = Field(default=None, description="Только эти правила; по умолчанию — все активные")

class AnalysisModeOut(BaseModel):
    id: AnalysisMode
    label: str
    available: bool
    description: str

class AnalysisModesOut(BaseModel):
    default_mode: AnalysisMode
    modes: list[AnalysisModeOut]
    configured_model: str | None = None

class AnalysisModelOut(BaseModel):
    id: str
    label: str
    provider: str
    provider_id: str
    description: str
    available: bool
    recommended: bool = False

class AnalysisModelsOut(BaseModel):
    default_model: str | None
    models: list[AnalysisModelOut]
    source: Literal["provider", "fallback"]
    warning: str | None = None

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
