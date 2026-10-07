"""Поиск по тексту документа с координатами совпадений (работает и для распознанных сканов)."""
from bisect import bisect_left, bisect_right

from app.schemas import Highlight, SearchHit
from app.services.quotes import clause_for, highlight_rects, join_tokens, normalize_token, tokenize_pages

_SNIPPET_TOKENS = 12


def search_pages(pages: list[dict], query: str, limit: int) -> tuple[list[SearchHit], int]:
    query_norm = " ".join(filter(None, (normalize_token(t) for t in query.split())))
    if not query_norm:
        return [], 0
    tokens = tokenize_pages(pages)
    haystack, starts = join_tokens(tokens)
    pages_by_number = {p["page_number"]: p for p in pages}

    hits: list[SearchHit] = []
    total = 0
    pos = haystack.find(query_norm)
    while pos != -1:
        total += 1
        if len(hits) < limit:
            first = max(bisect_right(starts, pos) - 1, 0)
            last = max(bisect_left(starts, pos + len(query_norm)) - 1, first)
            matched = tokens[first:last + 1]
            lo, hi = max(0, first - _SNIPPET_TOKENS), min(len(tokens), last + 1 + _SNIPPET_TOKENS)
            snippet_words = []
            for t in tokens[lo:hi]:
                words = pages_by_number[t.page]["words"]
                snippet_words.extend(words[wi][4] for wi in t.words)
            snippet = ("… " if lo > 0 else "") + " ".join(snippet_words) + (" …" if hi < len(tokens) else "")
            hits.append(SearchHit(
                page=matched[0].page,
                clause=clause_for(pages_by_number, tokens, first, last),
                snippet=snippet,
                highlights=[Highlight(**h) for h in highlight_rects(pages_by_number, matched)],
            ))
        pos = haystack.find(query_norm, pos + len(query_norm))
    return hits, total
