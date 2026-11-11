from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import AnalysisModelsOut, AnalysisModesOut, UserOut, UserProfileUpdate
from app.services.analysis_models import model_catalog
from app.services.analysis_modes import capabilities, default_analysis_mode
from app.services.document_quality import user_quality_settings

router = APIRouter(tags=["Система"])


@router.get("/api/analysis-modes", response_model=AnalysisModesOut, response_model_exclude_none=True,
            summary="Доступные режимы анализа и режим по умолчанию")
def analysis_modes():
    return capabilities()


@router.get("/api/analysis-models", response_model=AnalysisModelsOut, response_model_exclude_none=True,
            summary="Текстовые модели для анализа документов")
def analysis_models():
    return model_catalog()


@router.get("/api/health", summary="Проверка работоспособности")
def health(response: Response, db: Session = Depends(get_db)):
    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.rollback()
        database_ok = False
    redis_ok = False
    try:
        import redis

        with redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
            redis_ok = bool(client.ping())
    except Exception:  # noqa: BLE001
        pass
    healthy = database_ok and redis_ok
    if not healthy:
        response.status_code = 503
    return {
        "status": "ok" if healthy else "degraded",
        "database": database_ok,
        "queue": redis_ok,
        "default_mode": default_analysis_mode(),
        "llm": settings.llm_model if settings.llm_enabled else "heuristic (LLM не настроена)",
        "embeddings": settings.embedding_model_id,
        "ocr": settings.ocr_enabled,
    }


def _user_out(user: User) -> UserOut:
    initials = "".join(part[0] for part in user.full_name.split()[:2] if part).upper()
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, company_name=user.company_name,
                   role=user.role, initials=initials, quality_settings=user_quality_settings(user))


@router.get("/api/users/me", response_model=UserOut, summary="Текущий пользователь (аватар в шапке)")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.patch("/api/users/me", response_model=UserOut, summary="Сохранить данные профиля и настройки качества проверки")
def update_profile(body: UserProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if "full_name" in body.model_fields_set:
        user.full_name = body.full_name
    if "company_name" in body.model_fields_set:
        user.company_name = body.company_name or None
    if "quality_settings" in body.model_fields_set:
        user.quality_settings = body.quality_settings.model_dump(mode="json")
    db.commit()
    db.refresh(user)
    return _user_out(user)
