"""Гибридный поиск фрагментов документа под правило: вектор (pgvector) + полнотекстовый (russian), слияние RRF."""
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings


@dataclass
class RetrievedChunk:
    id: uuid.UUID
    chunk_index: int | None
    page_number: int
    page_end: int | None
    clause_title: str | None
    content: str
    score: float
    fts_hit: bool
    embedding: list[float] | None = None
    distance: float | None = None


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _parse_embedding(val) -> list[float] | None:
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        return [float(x) for x in val]
    if hasattr(val, "tolist"):
        return [float(x) for x in val.tolist()]
    if isinstance(val, str):
        cleaned = val.strip("[]() \t\n")
        if not cleaned:
            return None
        return [float(x) for x in cleaned.split(",") if x.strip()]
    return None


def compute_chunk_similarity(c1: RetrievedChunk, c2: RetrievedChunk) -> float:
    """Оценивает семантическое/текстовое сходство двух чанков в диапазоне [0.0, 1.0]."""
    # 1. Косинусное сходство векторных представлений (если доступны)
    if c1.embedding and c2.embedding and len(c1.embedding) == len(c2.embedding):
        v1 = np.asarray(c1.embedding, dtype=np.float32)
        v2 = np.asarray(c2.embedding, dtype=np.float32)
        norm1 = float(np.linalg.norm(v1))
        norm2 = float(np.linalg.norm(v2))
        if norm1 > 1e-6 and norm2 > 1e-6:
            cos_sim = float(np.dot(v1, v2) / (norm1 * norm2))
            return max(0.0, min(1.0, cos_sim))

    # 2. Текстовое сходство по токенам через rapidfuzz
    from rapidfuzz import fuzz
    ratio = fuzz.token_set_ratio(c1.content, c2.content) / 100.0
    return max(0.0, min(1.0, float(ratio)))


def apply_mmr(
    chunks: list[RetrievedChunk],
    top_k: int,
    lambda_param: float = 0.65,
    sim_threshold: float = 0.80,
) -> list[RetrievedChunk]:
    """Maximal Marginal Relevance: отбор разнообразных релевантных фрагментов.

    Исключает засорение контекста одинаковыми копиями повторяющихся приложений/разделов.
    Чанки, сходство которых к уже выбранным превышает sim_threshold (0.80),
    получают штраф за дублирование.
    """
    if len(chunks) <= top_k or top_k <= 0:
        return chunks

    max_score = max((c.score for c in chunks), default=1.0)
    if max_score <= 0:
        max_score = 1.0

    selected: list[RetrievedChunk] = [chunks[0]]
    remaining: list[RetrievedChunk] = list(chunks[1:])

    while len(selected) < top_k and remaining:
        best_candidate: RetrievedChunk | None = None
        best_mmr_score = -float("inf")
        best_idx = -1

        for idx, candidate in enumerate(remaining):
            # Нормализованный скор релевантности [0, 1]
            rel_score = candidate.score / max_score

            # Максимальное сходство с уже отобранными фрагментами
            max_sim = max(compute_chunk_similarity(candidate, sel) for sel in selected)

            # Штраф за дублирование при превышении порога (0.80)
            redundancy_penalty = 2.0 if max_sim >= sim_threshold else 0.0

            mmr_val = (lambda_param * rel_score) - ((1.0 - lambda_param) * max_sim) - redundancy_penalty

            if mmr_val > best_mmr_score:
                best_mmr_score = mmr_val
                best_candidate = candidate
                best_idx = idx

        if best_candidate is not None and best_idx >= 0:
            selected.append(best_candidate)
            remaining.pop(best_idx)
        else:
            break

    return selected


# «+ 0» в ORDER BY отключает HNSW-индекс: он глобальный по всем чанкам, и фильтр по документу
# после приблизительного поиска может отрезать нужные фрагменты. Внутри одного документа
# точный перебор быстрый (сотни чанков).
_HYBRID_SQL = text("""
WITH q AS (
    SELECT CAST(:embedding AS vector) AS emb,
           NULLIF(replace(plainto_tsquery('russian', :query)::text, '&', '|'), '')::tsquery AS tsq
),
vec AS (
    SELECT c.id,
           (c.embedding <=> q.emb) AS dist,
           row_number() OVER (ORDER BY (c.embedding <=> q.emb) + 0) AS r
    FROM document_chunks c, q
    WHERE c.document_id = :document_id AND c.embedding IS NOT NULL
      AND (c.embedding <=> q.emb) <= :max_distance
    ORDER BY (c.embedding <=> q.emb) + 0
    LIMIT :candidates
),
fts AS (
    SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC) AS r
    FROM document_chunks c, q
    WHERE c.document_id = :document_id AND q.tsq IS NOT NULL AND c.tsv @@ q.tsq
    ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC
    LIMIT :candidates
)
SELECT c.id, c.chunk_index, c.page_number, c.page_end, c.clause_title, c.content,
       c.embedding,
       COALESCE(1.0 / (60 + vec.r), 0) + COALESCE(1.0 / (60 + fts.r), 0) AS score,
       fts.id IS NOT NULL AS fts_hit,
       vec.dist AS distance
FROM document_chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN fts ON fts.id = c.id
WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
ORDER BY score DESC
LIMIT :candidates
""")


def hybrid_search(
    db: Session,
    document_id: uuid.UUID,
    query: str,
    embedding: list[float],
    top_k: int,
    max_distance: float | None = None,
) -> list[RetrievedChunk]:
    if max_distance is None:
        max_distance = settings.retrieval_max_distance
    rows = db.execute(_HYBRID_SQL, {
        "embedding": vector_literal(embedding),
        "query": query,
        "document_id": document_id,
        "candidates": max(top_k * 3, 12),
        "top_k": top_k,
        "max_distance": max_distance,
    }).mappings().all()
    candidate_chunks = [
        RetrievedChunk(
            id=row["id"],
            chunk_index=row["chunk_index"],
            page_number=row["page_number"],
            page_end=row["page_end"],
            clause_title=row["clause_title"],
            content=row["content"],
            score=float(row["score"]),
            fts_hit=bool(row["fts_hit"]),
            distance=float(row["distance"]) if row.get("distance") is not None else None,
            embedding=_parse_embedding(row.get("embedding")),
        )
        for row in rows
    ]
    selected_chunks = apply_mmr(candidate_chunks, top_k=top_k)
    # В контекст LLM — в порядке следования в документе: так модели проще понять структуру
    return sorted(selected_chunks, key=lambda c: (c.chunk_index is None, c.chunk_index or 0))

