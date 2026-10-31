import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(db: Session, user_id: uuid.UUID | None, action: str, entity_type: str,
               entity_id: uuid.UUID | None = None, details: dict | None = None) -> None:
    """Пишет запись в журнал аудита. Коммит — на стороне вызывающего."""
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details))
