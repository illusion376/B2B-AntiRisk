"""Проверка цитат LLM и поиск их координат в документе.

Точное совпадение подтверждает цитату; нечёткое совпадение служит только подсказкой
и никогда не считается проверенным. Строгий режим дополнительно привязывает цитату
к выбранному фрагменту и его страницам, сохраняя отрицания, числа и пунктуацию.
"""
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 82.0

_STRIP = "«»\"'“”„()[]{}.,;:!?…"
_CLAUSE_TOKEN = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,3}\.?$")
_SECTION_TOKEN = re.compile(r"^\d{1,2}$")  # «6.» в начале строки -> «6» после нормализации
# Число со знаком и десятичной частью — один токен: «1» не совпадёт с «11»,
# «0.1» или «-1». Остальная пунктуация тоже участвует в строгом сравнении.
_STRICT_LEXEME = re.compile(r"[+\-−]?\d+(?:[.,:/]\d+)*(?:[%‰])?|[^\W\d_]+|[^\w\s]|[\w]", re.UNICODE)
_WRAP = re.compile(r"([^\W\d_]{3,})[-\u00ad][ \t]*\r?\n[ \t]*([^\W\d_])", re.UNICODE)
_NEGATIONS = {"не", "ни", "без"}


def _dehyphenate_evidence(text: str, *, join_hard_wraps: bool = True) -> str:
    """Склеиваем только буквенный перенос строки, никогда числа/минус/«не-».

    Обычный дефис внутри строки сохраняется. Мягкий дефис U+00AD между буквами
    обозначает перенос и может быть удалён независимо от ширины строки.
    """
    def join(match: re.Match) -> str:
        left, right = match.groups()
        if left.casefold() in _NEGATIONS or not right.islower():
            return match.group()
        return left + right

    if join_hard_wraps:
        text = _WRAP.sub(join, text)
    return re.sub(r"(?<=[^\W\d_])\u00ad(?=[^\W\d_])", "", text)


def _strict_text_tokens(text: str, *, join_hard_wraps: bool = True) -> list[str]:
    return _STRICT_LEXEME.findall(_dehyphenate_evidence(text, join_hard_wraps=join_hard_wraps))


def _exact_span(haystack: list[str], needle: list[str], *, strict: bool = False) -> tuple[int, int] | None:
    if not needle:
        return None
    for first in range(len(haystack) - len(needle) + 1):
        if haystack[first:first + len(needle)] != needle:
            continue
        # Начало цитаты сразу после «не» превращает отрицание в утверждение.
        # Отдельно записанный знак числа также нельзя отбросить с края цитаты.
        if strict and first and (
            haystack[first - 1].casefold() in _NEGATIONS
            or (needle[0][:1].isdigit() and haystack[first - 1] in {"-", "+", "−", "±", "<", ">", "≤", "≥", "="})
        ):
            continue
        return first, first + len(needle) - 1
    return None


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


def _find(tokens: list[_Token], quote_norm: str, *, fuzzy: bool = True) -> tuple[int, int, float, bool] | None:
    if not tokens or not quote_norm:
        return None
    exact = _exact_span([token.norm for token in tokens], quote_norm.split())
    if exact:
        return *exact, 100.0, True
    if not fuzzy:
        return None
    haystack, starts = join_tokens(tokens)
    alignment = fuzz.partial_ratio_alignment(quote_norm, haystack, score_cutoff=FUZZY_THRESHOLD)
    if alignment is None:
        return None
    first, last = _token_span(starts, alignment.dest_start, alignment.dest_end)
    return first, last, alignment.score, False


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


def _strict_page_tokens(pages: list[dict], *, join_hard_wraps: bool = True) -> list[_Token]:
    tokens: list[_Token] = []
    for page in pages:
        words = page["words"]
        i = 0
        while i < len(words):
            text = str(words[i][4])
            indices = [i]
            if i + 1 < len(words) and words[i + 1][5] != words[i][5]:
                following = str(words[i + 1][4])
                wrapped = text + "\n" + following
                joined = _dehyphenate_evidence(wrapped, join_hard_wraps=join_hard_wraps)
                if "\n" not in joined:
                    text = joined
                    indices.append(i + 1)
            for norm in _strict_text_tokens(text, join_hard_wraps=join_hard_wraps):
                tokens.append(_Token(page["page_number"], indices, norm))
            i += len(indices)
    return tokens


def _original_text(pages_by_number: dict[int, dict], tokens: list[_Token], *, keep_lines: bool = False) -> str:
    parts: list[str] = []
    seen: set[tuple[int, int]] = set()
    previous_line: tuple[int, int] | None = None
    for token in tokens:
        words = pages_by_number[token.page]["words"]
        for wi in token.words:
            key = (token.page, wi)
            if key in seen:
                continue
            seen.add(key)
            line = (token.page, words[wi][5])
            if parts:
                parts.append("\n" if keep_lines and line != previous_line else " ")
            parts.append(words[wi][4])
            previous_line = line
    return "".join(parts)


def _strict_quote(pages: list[dict], quote: str, page_hint: tuple[int, int] | None,
                  candidate_text: str | None) -> QuoteMatch:
    empty = QuoteMatch(False, page_hint[0] if page_hint else None, None, None)
    # Без границ фрагмента невозможно подтвердить принадлежность доказательства.
    if candidate_text is None or not page_hint or page_hint[0] > page_hint[1]:
        return empty
    scoped_pages = [p for p in pages if page_hint[0] <= p["page_number"] <= page_hint[1]]
    # Сначала сохраняем буквальный дефис (включая составные слова на переносе),
    # затем допускаем склейку буквенного переноса. Пунктуация цитаты не удаляется.
    for join_hard_wraps in (False, True):
        needle = _strict_text_tokens(quote, join_hard_wraps=join_hard_wraps)
        if not any(any(char.isalpha() or char.isdigit() for char in part) for part in needle):
            return empty
        candidate = _strict_text_tokens(candidate_text, join_hard_wraps=join_hard_wraps)
        if _exact_span(candidate, needle, strict=True) is None:
            continue
        tokens = _strict_page_tokens(scoped_pages, join_hard_wraps=join_hard_wraps)
        found = _exact_span([token.norm for token in tokens], needle, strict=True)
        if found is not None:
            break
    else:
        return empty
    first, last = found
    matched = tokens[first:last + 1]
    pages_by_number = {p["page_number"]: p for p in scoped_pages}
    # Нумерация пунктов использует прежнюю нормализацию, независимо от сравнения цитат.
    clause_tokens = tokenize_pages(scoped_pages)
    offset = next((i for i, t in enumerate(clause_tokens)
                   if (t.page, t.words[-1]) >= (matched[0].page, matched[0].words[0])), 0)
    end = max((i for i, t in enumerate(clause_tokens)
               if (t.page, t.words[0]) <= (matched[-1].page, matched[-1].words[-1])), default=offset)
    return QuoteMatch(
        verified=True,
        page_number=matched[0].page,
        text=_original_text(pages_by_number, matched, keep_lines=True),
        clause=clause_for(pages_by_number, clause_tokens, offset, end),
        highlights=highlight_rects(pages_by_number, matched),
        score=100.0,
    )


def locate_quote(pages: list[dict], quote: str, page_hint: tuple[int, int] | None = None, *,
                 candidate_text: str | None = None, strict: bool = False) -> QuoteMatch:
    """Найти цитату; fuzzy-совпадения всегда возвращаются с verified=False.

    strict=True требует candidate_text и page_hint, точного совпадения в обоих
    источниках и сохраняет регистр, отрицания, числа, знаки и пунктуацию.
    Пробельное оформление и буквенные переносы строк не влияют на совпадение.
    Проверку минимальной длины содержательной цитаты выполняет вызывающий анализатор.
    """
    if strict:
        return _strict_quote(pages, quote, page_hint, candidate_text)
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
        # По всему документу после локального поиска — только точное совпадение.
        found = _find(scope, quote_norm, fuzzy=scope_index == 0)
        if not found:
            continue
        first, last, score, verified = found
        matched = scope[first:last + 1]
        offset = next(i for i, t in enumerate(all_tokens) if t is matched[0])
        return QuoteMatch(
            verified=verified,
            page_number=matched[0].page,
            text=_original_text(pages_by_number, matched),
            clause=clause_for(pages_by_number, all_tokens, offset, offset + len(matched) - 1),
            highlights=highlight_rects(pages_by_number, matched),
            score=score,
        )
    return QuoteMatch(False, page_hint[0] if page_hint else None, None, None)
