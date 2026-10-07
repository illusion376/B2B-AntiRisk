"""Проверка цитат LLM и поиск их координат в документе.

LLM может слегка исказить цитату (пробелы, кавычки, перенос строки, OCR-ошибки). Мы ищем
цитату в реальном тексте страницы — сначала точно, затем нечётко (rapidfuzz) — и в отчёт
кладём фрагмент именно из документа. Заодно получаем прямоугольники для подсветки
и номер пункта договора, в котором находится цитата.
"""
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 82.0

_STRIP = "«»\"'“”„()[]{}.,;:!?…"
_CLAUSE_TOKEN = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,3}\.?$")
_SECTION_TOKEN = re.compile(r"^\d{1,2}$")  # «6.» в начале строки -> «6» после нормализации


def normalize_token(token: str) -> str:
    return token.lower().replace("ё", "е").strip(_STRIP).replace("–", "-").replace("—", "-")


@dataclass
class _Token:
    page: int  # номер страницы, с 1
    words: list[int]  # индексы слов страницы (несколько при склейке переноса)
    norm: str


@dataclass
class QuoteMatch:
    verified: bool
    page_number: int | None
    text: str | None  # фрагмент документа, соответствующий цитате
    clause: str | None  # «6.2»
    highlights: list[dict] = field(default_factory=list)
    score: float = 0.0


def tokenize_pages(pages: list[dict]) -> list[_Token]:
    """pages: [{"page_number", "words": [[x0,y0,x1,y1,text,line], ...]}]"""
    tokens: list[_Token] = []
    for page in pages:
        words = page["words"]
        i = 0
        while i < len(words):
            text = words[i][4]
            idx = [i]
            # «исполне-» + «ния» на следующей строке -> «исполнения»
            if (text.endswith("-") and len(text) > 2 and i + 1 < len(words)
                    and words[i + 1][5] != words[i][5] and words[i + 1][4][:1].islower()):
                text = text[:-1] + words[i + 1][4]
                idx.append(i + 1)
            norm = normalize_token(text)
            if norm:
                tokens.append(_Token(page["page_number"], idx, norm))
            i += len(idx)
    return tokens


def join_tokens(tokens: list[_Token]) -> tuple[str, list[int]]:
    """Склеивает токены через пробел; starts[i] — позиция начала i-го токена."""
    starts, parts, pos = [], [], 0
    for t in tokens:
        starts.append(pos)
        parts.append(t.norm)
        pos += len(t.norm) + 1
    return " ".join(parts), starts


def _token_span(starts: list[int], begin: int, end: int) -> tuple[int, int]:
    """Индексы первого и последнего токена, пересекающих диапазон символов [begin, end)."""
    first = max(bisect_right(starts, begin) - 1, 0)
    last = max(bisect_left(starts, end) - 1, first)
    return first, last


def _find(tokens: list[_Token], quote_norm: str) -> tuple[int, int, float] | None:
    if not tokens or not quote_norm:
        return None
    haystack, starts = join_tokens(tokens)
    pos = haystack.find(quote_norm)
    if pos != -1:
        first, last = _token_span(starts, pos, pos + len(quote_norm))
        return first, last, 100.0
    alignment = fuzz.partial_ratio_alignment(quote_norm, haystack, score_cutoff=FUZZY_THRESHOLD)
    if alignment is None:
        return None
    first, last = _token_span(starts, alignment.dest_start, alignment.dest_end)
    return first, last, alignment.score


def highlight_rects(pages_by_number: dict[int, dict], tokens: list[_Token]) -> list[dict]:
    """Прямоугольники по строкам: соседние слова одной строки объединяются."""
    by_page: dict[int, dict[int, list[float]]] = {}
    for token in tokens:
        words = pages_by_number[token.page]["words"]
        for wi in token.words:
            x0, y0, x1, y1, _, line = words[wi]
            lines = by_page.setdefault(token.page, {})
            if line in lines:
                r = lines[line]
                lines[line] = [min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)]
            else:
                lines[line] = [x0, y0, x1, y1]
    return [{"page": page, "rects": list(lines.values())} for page, lines in by_page.items()]


def _starts_line(pages_by_number: dict[int, dict], token: _Token) -> bool:
    words = pages_by_number[token.page]["words"]
    wi = token.words[0]
    return wi == 0 or words[wi - 1][5] != words[wi][5]


def clause_for(pages_by_number: dict[int, dict], tokens: list[_Token], start: int, end: int) -> str | None:
    """Номер пункта («6.2»), к которому относится цитата tokens[start:end + 1].

    Ищем назад от начала цитаты номер пункта в начале строки, но не дальше заголовка раздела
    («6. ОТВЕТСТВЕННОСТЬ СТОРОН»): иначе цитата из заголовка получила бы пункт прошлого раздела.
    Если цитата сама начинается с заголовка — берём первый пункт внутри неё.
    """
    for i in range(start, max(-1, start - 600), -1):
        token = tokens[i]
        if not _starts_line(pages_by_number, token):
            continue
        if _CLAUSE_TOKEN.match(token.norm + "."):
            return token.norm
        original = pages_by_number[token.page]["words"][token.words[0]][4]
        if _SECTION_TOKEN.match(token.norm) and original.endswith("."):
            break
    for token in tokens[start:end + 1]:
        if _CLAUSE_TOKEN.match(token.norm + ".") and _starts_line(pages_by_number, token):
            return token.norm
    return None


def locate_quote(pages: list[dict], quote: str, page_hint: tuple[int, int] | None = None) -> QuoteMatch:
    """pages — все страницы документа по порядку; page_hint — (с, по) страницы чанка."""
    quote_norm = " ".join(filter(None, (normalize_token(t) for t in quote.split())))
    if not quote_norm:
        return QuoteMatch(False, None, None, None)
    pages_by_number = {p["page_number"]: p for p in pages}
    all_tokens = tokenize_pages(pages)

    candidates: list[list[_Token]] = []
    if page_hint:
        lo, hi = page_hint[0] - 1, page_hint[1] + 1
        candidates.append([t for t in all_tokens if lo <= t.page <= hi])
    candidates.append(all_tokens)

    for scope_index, scope in enumerate(candidates):
        if scope_index > 0:
            # По всему документу — только точное совпадение: нечёткий поиск по 50+ страницам дорог
            haystack, _ = join_tokens(scope)
            if quote_norm not in haystack:
                break
        found = _find(scope, quote_norm)
        if not found:
            continue
        first, last, score = found
        matched = scope[first:last + 1]
        original_words = []
        for t in matched:
            words = pages_by_number[t.page]["words"]
            original_words.extend(words[wi][4] for wi in t.words)
        offset = next(i for i, t in enumerate(all_tokens) if t is matched[0])
        return QuoteMatch(
            verified=True,
            page_number=matched[0].page,
            text=" ".join(original_words),
            clause=clause_for(pages_by_number, all_tokens, offset, offset + len(matched) - 1),
            highlights=highlight_rects(pages_by_number, matched),
            score=score,
        )
    return QuoteMatch(False, page_hint[0] if page_hint else None, None, None)
