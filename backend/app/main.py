import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analyses, documents, findings, history, projects, reports, rules, system
from app.config import settings
from app.migrations import run_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    run_migrations()
    yield


app = FastAPI(
    title="Светофор рисков документов — API",
    description="AI Procurement Copilot, кейс 1: проверка документации закупок (44-ФЗ / 223-ФЗ) "
                "по настраиваемым правилам с визуализацией рисков в формате «светофора».",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for module in (system, projects, analyses, documents, findings, rules, reports, history):
    app.include_router(module.router)
