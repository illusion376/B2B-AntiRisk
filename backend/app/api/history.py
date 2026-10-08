"""Раздел «История» и уведомления: журнал аудита в виде понятных записей (HistoryEntry во фронтенде)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import AuditLog, User
from app.schemas import HistoryEntry

router = APIRouter(prefix="/api/history", tags=["История"])

REPORT_MODES = {"brief": "Краткий отчёт", "detailed": "Подробный отчёт", "protocol": "Протокол разногласий",
                "annotated": "Документ с пометками"}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _join(*parts) -> str:
    return " · ".join(str(p) for p in parts if p)


def describe(action: str, d: dict) -> tuple[str, str]:
    """(заголовок, подробности) для записи журнала."""
    file, project = d.get("file"), d.get("project")
    match action:
        case "PROJECT_CREATED":
            return "Проект создан", d.get("title", "")
        case "PROJECT_UPDATED":
            return "Проект изменён", d.get("title", "")
        case "PROJECT_DELETED":
            return "Проект удалён", d.get("title", "")
        case "ANALYSIS_CREATED":
            count = d.get("documents") or 1
            documents = f"{count} {_plural(count, 'документ', 'документа', 'документов')} в архиве" if count > 1 else None
            return ("Файл добавлен в проект" if project else "Документ добавлен"), _join(project, file, documents)
        case "ANALYSIS_STARTED":
            return "Анализ запущен", _join(project, file)
        case "ANALYSIS_COMPLETED":
            rules = d.get("rules") or 0
            critical, warning, low = d.get("critical", 0), d.get("warning", 0), d.get("low", 0)
            return "Проверка документа завершена", _join(
                file, f"{rules} {_plural(rules, 'правило', 'правила', 'правил')}",
                f"{critical} {_plural(critical, 'критическое замечание', 'критических замечания', 'критических замечаний')}",
                f"{warning} требуют внимания", f"{low} с низким риском" if low else None,
            )
        case "ANALYSIS_FAILED":
            return "Проверка не удалась", _join(file, d.get("error"))
        case "ANALYSIS_RERUN" | "DOCUMENT_REANALYZE":
            return "Запущена повторная проверка", file or ""
        case "ANALYSIS_DELETED":
            return "Файл удалён", file or ""
        case "DOCUMENT_RENAMED":
            return "Документ переименован", f"{d.get('from')} → {d.get('to')}"
        case "FINDING_REVIEWED":
            return "Статус замечания изменён", _join(d.get("title"), d.get("status"))
        case "RULE_CREATED":
            return "Правило добавлено", d.get("title", "")
        case "RULE_UPDATED":
            return "Правило изменено", d.get("title", "")
        case "RULE_TOGGLED":
            return ("Правило включено" if d.get("enabled") else "Правило отключено"), d.get("title", "")
        case "RULE_DELETED":
            return "Правило удалено", d.get("title", "")
        case "REPORT_DOWNLOADED":
            return "Отчёт скачан", _join(REPORT_MODES.get(d.get("mode"), d.get("mode")), str(d.get("format", "")).upper())
    return action, ""


@router.get("", response_model=list[HistoryEntry],
            summary="История действий пользователя (для колокольчика: actions=ANALYSIS_COMPLETED,ANALYSIS_FAILED)")
def history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actions: str | None = Query(None, description="Фильтр по типам событий через запятую"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    if actions:
        query = query.where(AuditLog.action.in_([a.strip().upper() for a in actions.split(",")]))
    entries = []
    for log in db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)):
        title, detail = describe(log.action, log.details or {})
        entries.append(HistoryEntry(id=log.id, action=log.action, title=title, detail=detail, time=log.created_at,
                                    entity_type=log.entity_type, entity_id=log.entity_id))
    return entries
