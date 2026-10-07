"""Общие зависимости и сборка ответов API в терминах фронтенда."""
import uuid
from collections import defaultdict

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Analysis, Document, Project, RiskFinding, User, visible_findings
from app.schemas import AnalysisOut, DocumentOut, FindingOut, ProjectFileOut, ProjectOut, SeverityCounts
from app.services.scoring import risk_score, traffic_light
from app.vocab import REVIEW_TO_API, SEVERITY_TO_API

# Стадии пайплайна -> стадия и подпись для интерфейса
_STAGE_LABELS = {
    "QUEUED": ("queued", "В очереди"),
    "CONVERTING": ("processing", "Подготовка документа"),
    "OCR": ("processing", "Распознавание текста"),
    "VECTORIZING": ("processing", "Индексация"),
    "ANALYZING": ("processing", "Проверка правилами"),
    "COMPLETED": ("ready", "Обработано"),
    "FAILED": ("failed", "Ошибка обработки"),
    "UNSUPPORTED": ("unsupported", "Формат не поддерживается"),
}


def stage(status: str) -> tuple[str, str]:
    return _STAGE_LABELS.get(status, ("processing", "Обрабатывается"))


def current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, description="ID пользователя; без заголовка — демо-пользователь"),
) -> User:
    """Упрощённая идентификация для прототипа: полноценная авторизация (SSO/JWT) подключается здесь."""
    try:
        user_id = uuid.UUID(x_user_id or settings.default_user_id)
    except ValueError as exc:
        raise HTTPException(400, "Некорректный X-User-Id") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "Пользователь не найден")
    return user


def _owned(owner_id: uuid.UUID | None, user: User) -> bool:
    return owner_id in (None, user.id) or user.role == "ADMIN"


def get_project_or_404(db: Session, project_id: uuid.UUID, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or not _owned(project.user_id, user):
        raise HTTPException(404, "Проект не найден")
    return project


def get_analysis_or_404(db: Session, analysis_id: uuid.UUID, user: User) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or not _owned(analysis.user_id, user):
        raise HTTPException(404, "Файл не найден")
    return analysis


def get_document_or_404(db: Session, document_id: uuid.UUID, user: User) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Документ не найден")
    get_analysis_or_404(db, document.analysis_id, user)
    return document


# ---------- подсчёты ----------

def _counts(db: Session, group_column, filter_clause) -> dict:
    active = RiskFinding.review_status != "DISMISSED"
    rows = db.execute(
        select(
            group_column,
            func.count().filter(RiskFinding.severity == "RED", active),
            func.count().filter(RiskFinding.severity == "YELLOW", active),
            func.count().filter(RiskFinding.severity == "LOW", active),
            func.count().filter(RiskFinding.severity == "GREEN"),
            func.count().filter(RiskFinding.severity != "GREEN", RiskFinding.review_status == "NEW"),
            func.count(func.distinct(RiskFinding.rule_id)),
        ).where(filter_clause, visible_findings()).group_by(group_column)
    ).all()
    return {r[0]: (SeverityCounts(critical=r[1], warning=r[2], low=r[3], ok=r[4], unseen=r[5]), r[6]) for r in rows}


def counts_by_document(db: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[SeverityCounts, int]]:
    return _counts(db, RiskFinding.document_id, RiskFinding.document_id.in_(document_ids)) if document_ids else {}


def counts_by_analysis(db: Session, analysis_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[SeverityCounts, int]]:
    return _counts(db, RiskFinding.analysis_id, RiskFinding.analysis_id.in_(analysis_ids)) if analysis_ids else {}


def _sum(counts: list[SeverityCounts]) -> SeverityCounts:
    total = SeverityCounts()
    for c in counts:
        for field in SeverityCounts.model_fields:
            setattr(total, field, getattr(total, field) + getattr(c, field))
    return total


def _has_results(counts: SeverityCounts, rules_checked: int) -> bool:
    # После отклонения всех замечаний счётчики рисков обнуляются, но проверки остаются.
    return rules_checked > 0 or any((counts.critical, counts.warning, counts.low, counts.ok))


def light(counts: SeverityCounts, finished: bool, rules_checked: int) -> str | None:
    if not finished or not _has_results(counts, rules_checked):
        return None
    return SEVERITY_TO_API[traffic_light(["RED"] * counts.critical + ["YELLOW"] * counts.warning)]


# ---------- сборка ответов ----------

def document_out(doc: Document, counts: tuple[SeverityCounts, int] | None = None) -> DocumentOut:
    severity_counts, rules_checked = counts or (SeverityCounts(), 0)
    out = DocumentOut.model_validate(doc)
    out.phase, out.label = stage(doc.status)
    out.counts = severity_counts
    out.rules_checked = rules_checked
    out.traffic_light = light(severity_counts, doc.status == "COMPLETED", rules_checked)
    # Считаем по тем же видимым замечаниям, что и светофор: выключенные правила
    # и отклонённые замечания не должны оставлять устаревший индекс риска.
    out.risk_score = risk_score(
        ["RED"] * severity_counts.critical + ["YELLOW"] * severity_counts.warning + ["LOW"] * severity_counts.low
    ) if out.traffic_light is not None else None
    out.has_preview = bool(doc.preview_path)
    return out


def analyses_out(db: Session, analyses: list[Analysis]) -> list[AnalysisOut]:
    files = {file.id: file for file in project_files_out(db, analyses)}
    result = []
    for analysis in analyses:
        out = AnalysisOut.model_validate(analysis)
        file = files[analysis.id]
        out.counts, out.rules_checked = file.counts, file.rules_checked
        out.traffic_light, out.risk_score = file.traffic_light, file.risk_score
        out.documents_total = len(file.documents)
        out.documents_supported = sum(doc.status != "UNSUPPORTED" for doc in file.documents)
        result.append(out)
    return result


def project_files_out(db: Session, analyses: list[Analysis]) -> list[ProjectFileOut]:
    """Файлы проекта: один файл = один анализ; у ZIP в documents — содержимое архива."""
    ids = [a.id for a in analyses]
    analysis_counts = counts_by_analysis(db, ids)
    docs_by_analysis: dict[uuid.UUID, list[Document]] = defaultdict(list)
    if ids:
        for doc in db.scalars(select(Document).where(Document.analysis_id.in_(ids))
                              .order_by(func.coalesce(Document.relative_path, Document.file_name))):
            docs_by_analysis[doc.analysis_id].append(doc)
    doc_counts = counts_by_document(db, [d.id for docs in docs_by_analysis.values() for d in docs])

    files = []
    for analysis in analyses:
        severity_counts, rules_checked = analysis_counts.get(analysis.id, (SeverityCounts(), 0))
        phase, label = stage(analysis.analysis_status)
        if phase == "processing":
            label = f"{label} · {analysis.progress}%"
        documents = [document_out(d, doc_counts.get(d.id)) for d in docs_by_analysis[analysis.id]]
        supported = [doc for doc in documents if doc.status != "UNSUPPORTED"]
        finished = analysis.analysis_status == "COMPLETED" and bool(supported) and all(
            doc.traffic_light is not None for doc in supported
        )
        scores = [doc.risk_score for doc in supported if doc.risk_score is not None]
        files.append(ProjectFileOut(
            id=analysis.id,
            name=analysis.original_filename,
            type=analysis.file_type,
            size=analysis.file_size,
            added_at=analysis.created_at,
            phase=phase,
            label=label,
            progress=analysis.progress,
            status=analysis.analysis_status,
            error_message=analysis.error_message,
            risk_score=max(scores) if finished and scores else None,
            traffic_light=light(severity_counts, finished, rules_checked),
            counts=severity_counts,
            rules_checked=rules_checked,
            documents=documents,
        ))
    return files


def projects_out(db: Session, projects: list[Project]) -> list[ProjectOut]:
    project_ids = [p.id for p in projects]
    analyses_by_project: dict[uuid.UUID, list[Analysis]] = defaultdict(list)
    if project_ids:
        for analysis in db.scalars(select(Analysis).where(Analysis.project_id.in_(project_ids))
                                   .order_by(Analysis.created_at)):
            analyses_by_project[analysis.project_id].append(analysis)
    all_files = project_files_out(db, [a for items in analyses_by_project.values() for a in items])
    files_by_id = {f.id: f for f in all_files}

    result = []
    for project in projects:
        files = [files_by_id[a.id] for a in analyses_by_project[project.id]]
        finished = bool(files) and all(f.traffic_light is not None for f in files)
        counts = _sum([f.counts for f in files])
        result.append(ProjectOut(
            id=project.id,
            title=project.title,
            description=project.description,
            created_at=project.created_at,
            updated_at=project.updated_at,
            files=files,
            processing_count=sum(f.phase in ("queued", "processing") for f in files),
            counts=counts,
            traffic_light=light(counts, finished, sum(f.rules_checked for f in files)),
        ))
    return result


def finding_out(f: RiskFinding) -> FindingOut:
    """Номер замечания в документе не меняется при фильтрации: sort_index выставляется при сохранении
    (критические -> внимание -> низкий -> ok), поэтому у всех, кроме «ok», sort_index + 1 — сплошная нумерация."""
    return FindingOut(
        id=f.id,
        number=f.sort_index + 1 if f.severity != "GREEN" else None,
        document_id=f.document_id,
        rule_id=f.rule_id,
        title=f.title,
        description=f.short_description or "",
        severity=SEVERITY_TO_API.get(f.severity, "warning"),
        category=f.category or "",
        clause=f.clause or "",
        page=f.page_number,
        quote=f.exact_quote or "",
        recommendation=f.counter_proposal or "",
        comment=f.comment,
        legal_reference=f.legal_reference,
        highlights=f.highlights or [],
        quote_verified=f.quote_verified,
        confidence=f.confidence,
        source=f.source,
        status=REVIEW_TO_API.get(f.review_status, "unseen"),
        reviewer_comment=f.reviewer_comment,
        reviewed_at=f.reviewed_at,
        created_at=f.created_at,
    )
