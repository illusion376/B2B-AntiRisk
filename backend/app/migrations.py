"""Применение SQL-миграций из database/migrations поверх базовой схемы database/init-db.sql.

Каждый файл применяется один раз (учёт в schema_migrations). API и воркер стартуют
одновременно, поэтому миграции выполняются под advisory lock.
"""
import logging
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.db import engine

log = logging.getLogger(__name__)

_LOCK_KEY = 873_215_001


def _migrations_dir() -> Path | None:
    candidates = [
        settings.migrations_dir,
        Path(__file__).resolve().parents[2] / "database" / "migrations",  # локальный запуск из репозитория
    ]
    return next((p for p in candidates if p.is_dir()), None)


def run_migrations() -> None:
    directory = _migrations_dir()
    if directory is None:
        log.warning("Каталог миграций не найден, пропускаю")
        return
    files = sorted(directory.glob("*.sql"))

    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " filename VARCHAR(255) PRIMARY KEY,"
                " applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)"
            ))
            conn.commit()
            applied = {row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations"))}
            for path in files:
                if path.name in applied:
                    continue
                log.info("Применяю миграцию %s", path.name)
                # Курсор драйвера без параметров: в файле несколько выражений и символы «%»
                with conn.connection.dbapi_connection.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.execute(text("INSERT INTO schema_migrations (filename) VALUES (:f)"), {"f": path.name})
                conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            conn.commit()
