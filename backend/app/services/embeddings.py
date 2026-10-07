"""Эмбеддинги текста размерности 1024 (под колонку vector(1024)).

* Если задан EMBEDDING_BASE_URL — OpenAI-совместимый /embeddings (Ollama + bge-m3, vLLM, OpenAI и т. д.).
* Иначе — локальный хэш-эмбеддинг по символьным n-граммам: работает без сети и GPU,
  качество ниже, но вместе с полнотекстовым поиском (гибридный retrieval) этого хватает для демо.
"""
import hashlib
import logging
import re

import httpx
import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _hash_embedding(text: str, dim: int) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    for token in _TOKEN_RE.findall(text.lower()):
        # Грубая «основа» слова: первые 6 букв, чтобы «штраф/штрафа/штрафов» совпадали
        stem = token[:6]
        features = [f"w:{stem}"]
        padded = f"#{token}#"
        features += [f"g:{padded[i:i + 4]}" for i in range(max(1, len(padded) - 3))]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "little")
            sign = 1.0 if h & 1 else -1.0
            vec[(h >> 1) % dim] += sign * (2.0 if feature.startswith("w:") else 1.0)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, max=20),
    reraise=True,
)
def _remote_batch(client: httpx.Client, texts: list[str]) -> list[list[float]]:
    payload: dict = {"model": settings.embedding_model, "input": texts}
    if settings.embedding_send_dimensions:
        payload["dimensions"] = settings.embedding_dim
    response = client.post("/embeddings", json=payload)
    if response.status_code >= 500 or response.status_code == 429:
        response.raise_for_status()
    if response.status_code >= 400:
        raise EmbeddingError(f"Embeddings API {response.status_code}: {response.text[:300]}")
    data = sorted(response.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    dim = settings.embedding_dim
    if not settings.embedding_base_url:
        return [_hash_embedding(t, dim) for t in texts]

    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"} if settings.embedding_api_key else {}
    vectors: list[list[float]] = []
    with httpx.Client(base_url=settings.embedding_base_url.rstrip("/"), headers=headers, timeout=120) as client:
        for start in range(0, len(texts), settings.embedding_batch_size):
            batch = [t[:8000] for t in texts[start:start + settings.embedding_batch_size]]
            vectors.extend(_remote_batch(client, batch))

    for vec in vectors:
        if len(vec) != dim:
            raise EmbeddingError(
                f"Модель эмбеддингов вернула размерность {len(vec)}, а в БД vector({dim}). "
                "Используйте модель на 1024 измерения (bge-m3, multilingual-e5-large) "
                "или EMBEDDING_SEND_DIMENSIONS=true для text-embedding-3-*"
            )
    return vectors


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
