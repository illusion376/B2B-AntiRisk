from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import UserOut

router = APIRouter(tags=["Система"])


@router.get("/api/health", summary="Проверка работоспособности")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    redis_ok = True
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
    except Exception:  # noqa: BLE001
        redis_ok = False
    return {
        "status": "ok" if redis_ok else "degraded",
        "database": True,
        "queue": redis_ok,
        "llm": settings.llm_model if settings.llm_enabled else "heuristic (LLM не настроена)",
        "embeddings": settings.embedding_model_id,
        "ocr": settings.ocr_enabled,
    }


@router.get("/api/users/me", response_model=UserOut, summary="Текущий пользователь (аватар в шапке)")
def me(user: User = Depends(current_user)):
    initials = "".join(part[0] for part in user.full_name.split()[:2] if part).upper()
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, company_name=user.company_name,
                   role=user.role, initials=initials)
