"""Гибридный поиск фрагментов документа под правило: вектор (pgvector) + полнотекстовый (russian), слияние RRF."""
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


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


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


# «+ 0» в ORDER BY отключает HNSW-индекс: он глобальный по всем чанкам, и фильтр по документу
# после приблизительного поиска может отрезать нужные фрагменты. Внутри одного документа
# точный перебор быстрый (сотни чанков).
_HYBRID_SQL = text("""
WITH q AS (
    SELECT CAST(:embedding AS vector) AS emb,
           NULLIF(replace(plainto_tsquery('russian', :query)::text, '&', '|'), '')::tsquery AS tsq
),
vec AS (
    SELECT c.id, row_number() OVER (ORDER BY (c.embedding <=> q.emb) + 0) AS r
    FROM document_chunks c, q
    WHERE c.document_id = :document_id AND c.embedding IS NOT NULL
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
       COALESCE(1.0 / (60 + vec.r), 0) + COALESCE(1.0 / (60 + fts.r), 0) AS score,
       fts.id IS NOT NULL AS fts_hit
FROM document_chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN fts ON fts.id = c.id
WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
ORDER BY score DESC
LIMIT :top_k
""")


def hybrid_search(
    db: Session, document_id: uuid.UUID, query: str, embedding: list[float], top_k: int
) -> list[RetrievedChunk]:
    rows = db.execute(_HYBRID_SQL, {
        "embedding": vector_literal(embedding),
        "query": query,
        "document_id": document_id,
        "candidates": max(top_k * 3, 10),
        "top_k": top_k,
    }).mappings().all()
    chunks = [RetrievedChunk(**row) for row in rows]
    # В контекст LLM — в порядке следования в документе: так модели проще понять структуру
    return sorted(chunks, key=lambda c: (c.chunk_index is None, c.chunk_index or 0))
