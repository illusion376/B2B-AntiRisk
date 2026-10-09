from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Инфраструктура ---
    database_url: str = "postgresql+psycopg://postgres:secret_password@localhost:5432/b2b_procurement"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("./storage")
    cors_origins: str = "*"  # через запятую
    migrations_dir: Path = Path(__file__).resolve().parent.parent / "migrations"

    # --- Ограничения загрузки ---
    max_upload_mb: int = 100
    max_archive_files: int = 300
    max_archive_unpacked_mb: int = 1024  # защита от zip-бомб
    max_archive_depth: int = 2  # вложенные архивы

    # --- OCR ---
    ocr_enabled: bool = True
    ocr_languages: str = "rus+eng"
    ocr_dpi: int = 300
    ocr_threads: int = 4
    ocr_min_text_chars: int = 40  # меньше символов на странице -> считаем страницу сканом
    tessdata_prefix: str | None = None

    # --- Конвертация docx/doc/rtf -> pdf ---
    soffice_bin: str = "soffice"
    convert_timeout_s: int = 180

    # --- Чанкинг ---
    chunk_max_chars: int = 1400
    chunk_min_chars: int = 250

    # --- Эмбеддинги (OpenAI-совместимый API: Ollama, vLLM, OpenAI, Yandex и т. п.) ---
    embedding_base_url: str | None = None  # пусто -> локальный хэш-эмбеддинг (без внешних сервисов)
    embedding_api_key: str | None = None
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_send_dimensions: bool = False  # для text-embedding-3-* у OpenAI
    embedding_batch_size: int = 32

    # --- LLM через ProxyAPI; модели не загружаются на сервер ---
    llm_base_url: str | None = "https://api.proxyapi.ru/v1"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-4.1-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = Field(default=8192, ge=1)
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    llm_timeout_s: int = Field(default=120, gt=0)
    llm_concurrency: int = Field(default=6, ge=1)
    llm_json_mode: bool = True  # response_format={"type": "json_object"}

    # --- Анализ ---
    # auto: настроенная LLM, иначе поиск по словам без локальной модели.
    # nli принимается для понятной ошибки в старых конфигурациях, но отключён.
    analysis_engine: Literal["auto", "llm", "nli", "keyword"] = "auto"
    retrieval_top_k: int = Field(default=4, ge=1)
    default_user_id: str = "00000000-0000-0000-0000-000000000001"

    # --- Поиск без LLM ---
    # Старое значение nli принимается только для понятной ошибки при запуске.
    heuristic_engine: Literal["nli", "keyword"] = "keyword"
    nli_model_name: str = "cointegrated/rubert-base-cased-nli-threeway"
    nli_threshold: float = 0.5  # минимальная вероятность entailment для фиксации риска
    nli_batch_size: int = 16
    nli_device: str = "cpu"
    nli_quantize: bool = True  # dynamic INT8 квантование (экономит память в пределах 2 ГБ ОЗУ)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_enabled(self) -> bool:
        return all(value and value.strip() for value in (self.llm_base_url, self.llm_model, self.llm_api_key))

    @property
    def embedding_model_id(self) -> str:
        """Идентификатор, по которому кэшируются эмбеддинги правил."""
        if not self.embedding_base_url:
            return f"local-hash-{self.embedding_dim}"
        return f"{self.embedding_model}@{self.embedding_dim}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
