"""Разбор структуры договора: разделы и пункты (для навигации и цитирования) и нарезка на чанки."""
import re
from dataclasses import dataclass

from app.config import settings
from app.services.extraction import PageContent, dehyphenate

# «6. ОТВЕТСТВЕННОСТЬ СТОРОН», «Раздел 6. Ответственность сторон», «Статья 6»
_SECTION_RE = re.compile(
    r"^\s*(?:(?:раздел|статья|глава)\s+)?(?P<num>\d{1,2}|[IVXLC]{1,6})\.?\s+(?P<title>[^\d\W][^\n]{2,120})$",
    re.IGNORECASE,
)
# «6.2.», «6.2», «8.1.1.» в начале строки
_CLAUSE_RE = re.compile(r"^\s*(?P<num>\d{1,2}(?:\.\d{1,3}){1,3})\.?\s+(?P<rest>\S.*)$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+(?=[А-ЯЁA-Z0-9«\"(])")


@dataclass
class Segment:
    page_start: int
    page_end: int
    clause: str | None  # «6.2»
    section: str | None  # «6. Ответственность сторон»
    text: str


@dataclass
class Chunk:
    index: int
    page_start: int
    page_end: int
    clause_title: str | None
    content: str

    @property
    def embedding_text(self) -> str:
        return f"{self.clause_title}\n{self.content}" if self.clause_title else self.content


def _is_section_heading(line: str) -> re.Match | None:
    m = _SECTION_RE.match(line)
    if not m:
        return None
    title = m.group("title").strip()
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 4 or title.endswith((",", ";")):
        return None
    is_upper = sum(c.isupper() for c in letters) / len(letters) > 0.7
    explicit = line.strip().lower().startswith(("раздел", "статья", "глава"))
    # Заголовок: КАПСОМ, явное «Раздел N» или короткая фраза с заглавной буквы без точки в конце
    short_title = len(title) <= 60 and len(title.split()) <= 6 and title[0].isupper() and not title.endswith(".")
    if is_upper or explicit or short_title:
        return m
    return None


def section_title(match: re.Match) -> str:
    title = match.group("title").strip().rstrip(".")
    if title.isupper():
        title = title.capitalize()
    return f"{match.group('num')}. {title}"


def split_segments(pages: list[PageContent]) -> list[Segment]:
    segments: list[Segment] = []
    current: Segment | None = None
    section: str | None = None

    def flush() -> None:
        if current and current.text.strip():
            current.text = dehyphenate(current.text.strip())
            segments.append(current)

    for page in pages:
        for line in page.text.splitlines():
            if not line.strip():
                continue
            clause_m = _CLAUSE_RE.match(line)
            section_m = None if clause_m else _is_section_heading(line)
            if section_m:
                flush()
                section = section_title(section_m)
                current = Segment(page.page_number, page.page_number, None, section, line.strip())
            elif clause_m:
                flush()
                current = Segment(page.page_number, page.page_number, clause_m.group("num"), section, line.strip())
            elif current is None:
                current = Segment(page.page_number, page.page_number, None, section, line.strip())
            else:
                current.text += "\n" + line.strip()
                current.page_end = page.page_number
    flush()
    return segments


def build_outline(segments: list[Segment]) -> list[dict]:
    """Дерево для вкладки «Навигация»: разделы и их пункты с номерами страниц."""
    outline: list[dict] = []
    seen_sections: set[str] = set()
    for seg in segments:
        if seg.clause is None and seg.section and seg.section not in seen_sections:
            seen_sections.add(seg.section)
            outline.append({"title": seg.section, "page": seg.page_start, "clauses": []})
        elif seg.clause and seg.clause.count(".") == 1:
            preview = seg.text.split("\n", 1)[0]
            preview = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", preview)
            entry = {"clause": seg.clause, "title": preview[:90], "page": seg.page_start}
            if outline:
                outline[-1]["clauses"].append(entry)
            else:
                outline.append({"title": None, "page": seg.page_start, "clauses": [entry]})
    return outline


def _clause_title(segs: list[Segment]) -> str | None:
    clauses = [s.clause for s in segs if s.clause]
    section = next((s.section for s in segs if s.section), None)
    if clauses:
        label = f"п. {clauses[0]}" if len(clauses) == 1 else f"пп. {clauses[0]}–{clauses[-1]}"
    else:
        label = None
    parts = [p for p in (section, label) if p]
    return " › ".join(parts)[:255] if parts else None


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = _SENTENCE_SPLIT.split(text)
    parts: list[str] = []
    buf = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # очень длинное «предложение» (таблица, перечень)
            if buf:
                parts.append(buf)
                buf = ""
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            parts.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if buf and len(buf) + len(sentence) + 1 > max_chars:
            parts.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}" if buf else sentence
    if buf:
        parts.append(buf)
    return parts


def build_chunks(segments: list[Segment]) -> list[Chunk]:
    max_chars, min_chars = settings.chunk_max_chars, settings.chunk_min_chars
    chunks: list[Chunk] = []
    group: list[Segment] = []

    def emit() -> None:
        if not group:
            return
        text = "\n".join(s.text for s in group)
        title = _clause_title(group)
        page_start, page_end = group[0].page_start, group[-1].page_end
        for part in _split_long(text, max_chars):
            chunks.append(Chunk(len(chunks), page_start, page_end, title, part))
        group.clear()

    for seg in segments:
        group_len = sum(len(s.text) for s in group)
        same_section = not group or group[-1].section == seg.section
        if group and (not same_section or group_len >= min_chars or group_len + len(seg.text) > max_chars):
            emit()
        group.append(seg)
    emit()
    return chunks


_LAW_44 = re.compile(r"44\s*-\s*ФЗ|№\s*44\s*-?\s*ФЗ|от\s+05\.04\.2013", re.IGNORECASE)
_LAW_223 = re.compile(r"223\s*-\s*ФЗ|№\s*223\s*-?\s*ФЗ|от\s+18\.07\.2011", re.IGNORECASE)


def detect_law_type(text: str) -> str | None:
    n44, n223 = len(_LAW_44.findall(text)), len(_LAW_223.findall(text))
    if n44 == n223 == 0:
        return None
    return "44-FZ" if n44 >= n223 else "223-FZ"


def _join_line(text: str, line: str) -> str:
    """Склейка строк абзаца с учётом переноса слов «исполне-» + «ния»."""
    if text.endswith("-") and line[:1].islower():
        return text[:-1] + line
    return f"{text} {line}"


def page_sections(pages: list[tuple[int, str]], page_number: int) -> list[dict]:
    """Текст страницы разделами и пунктами — для HTML-просмотрщика фронтенда (getPageSections).

    pages — [(номер, текст)] всех страниц по порядку: раздел и пункт, начавшиеся раньше,
    переносятся на запрошенную страницу. Возвращает
    [{"title": "6. ОТВЕТСТВЕННОСТЬ СТОРОН", "paragraphs": [{"clause": "6.2", "text": "..."}]}].
    """
    sections: list[dict] = []
    section_heading = ""
    clause = ""
    paragraph_open = False  # следующая строка без номера продолжает текущий абзац

    for number, text in pages:
        if number > page_number:
            break
        on_page = number == page_number
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            clause_m = _CLAUSE_RE.match(line)
            section_m = None if clause_m else _is_section_heading(line)
            if section_m:
                section_heading, clause, paragraph_open = line, "", False
                if on_page:
                    sections.append({"title": line, "paragraphs": []})
                continue
            if not on_page:
                if clause_m:
                    clause = clause_m.group("num")
                continue
            if not sections:
                sections.append({"title": section_heading, "paragraphs": []})
            paragraphs = sections[-1]["paragraphs"]
            if clause_m:
                clause = clause_m.group("num")
                paragraphs.append({"clause": clause, "text": line})
                paragraph_open = True
            elif paragraph_open and paragraphs:
                paragraphs[-1]["text"] = _join_line(paragraphs[-1]["text"], line)
            else:
                # Начало страницы — продолжение пункта с прошлой страницы, либо текст без нумерации
                paragraphs.append({"clause": clause, "text": line})
                paragraph_open = True
    return sections
