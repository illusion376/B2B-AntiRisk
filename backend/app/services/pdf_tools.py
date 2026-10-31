"""Операции PyMuPDF в процессе API. MuPDF не потокобезопасен, а FastAPI выполняет sync-эндпоинты
в пуле потоков, поэтому все вызовы сериализуются через общий lock."""
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pymupdf as fitz

from app.services import storage

PDF_LOCK = threading.Lock()

_COLORS = {"RED": (0.90, 0.22, 0.21), "YELLOW": (0.98, 0.70, 0.10), "LOW": (0.40, 0.73, 0.42),
           "GREEN": (0.26, 0.63, 0.28)}
_SEVERITY_LABEL = {"RED": "Критично", "YELLOW": "Внимание", "LOW": "Низкий риск", "GREEN": "Без рисков"}

def thumbnail(pdf_path: Path, analysis_id: uuid.UUID, document_id: uuid.UUID, page_number: int, width: int) -> Path:
    target = storage.subdir(analysis_id, "thumbs") / f"{document_id}_{page_number}_{width}.png"
    if target.exists():
        return target
    with PDF_LOCK, fitz.open(pdf_path) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise IndexError(page_number)
        page = doc[page_number - 1]
        zoom = width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(target)
    return target

_MARGIN = 190
_NOTE_CSS = "* {font-family: sans-serif; font-size: 7.5pt; line-height: 1.25;} .meta {color: #555555;}"
_PAGE_BOTTOM = 12

@dataclass(eq=False)
class _Note:
    finding: dict
    page_index: int | None = None
    rect: fitz.Rect | None = None

def _hex(color: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in color)

def _note_html(f: dict, with_location: bool = False) -> str:
    color = _hex(_COLORS.get(f["severity"], _COLORS["YELLOW"]))
    parts = [f"<b style='color: {color}'>№{f['number']} · {_SEVERITY_LABEL.get(f['severity'], '')}</b>"
             f"<br><b>{escape(f['title'])}</b>"]
    if with_location:
        where = ", ".join(x for x in (f"п. {f['clause']}" if f.get("clause") else None,
                                      f"стр. {f['page_number']}" if f.get("page_number") else None) if x)
        if where:
            parts.append(f"<span class='meta'>{escape(where)}</span>")
    parts.append(escape(f.get("comment") or ""))
    if f.get("counter_proposal"):
        parts.append(f"<b>Рекомендация:</b> {escape(f['counter_proposal'])}")
    return "<br>".join(parts)

def _put_html(page, rect: fitz.Rect, html: str, scale_low: float = 1) -> float | None:
    """Пишет HTML в прямоугольник; возвращает занятую высоту или None, если текст не помещается.

    scale_low=1 — без уменьшения шрифта: не поместившийся текст не пишется вовсе.
    """
    spare, scale = page.insert_htmlbox(rect, html, css=_NOTE_CSS, scale_low=scale_low)
    if spare < 0:
        return None
    return rect.height - spare if scale >= 1 else rect.height

def _widen(page, width: float) -> None:
    """Добавляет поле справа; координаты содержимого и подсветки не меняются."""
    media, crop = page.mediabox, page.cropbox
    page.set_mediabox(fitz.Rect(media.x0, media.y0, media.x1 + width, media.y1))
    page.set_cropbox(fitz.Rect(crop.x0, crop.y0, crop.x1 + width, crop.y1))

def _marker(page, rect: fitz.Rect, number, color, content_width: float, placed: list[fitz.Rect]) -> None:
    """Цветная метка с номером замечания на правом краю страницы, на уровне первой строки цитаты.

    Метки замечаний на одной строке выстраиваются влево, а не накладываются друг на друга.
    """
    label = str(number)
    w = 5 + 4.2 * len(label)
    box = fitz.Rect(content_width - w - 4, rect.y0, content_width - 4, rect.y0 + 10)
    while any(box.intersects(other) for other in placed):
        box = fitz.Rect(box.x0 - w - 2, box.y0, box.x1 - w - 2, box.y1)
    placed.append(box)
    page.draw_rect(box, color=None, fill=color)
    page.insert_text(fitz.Point(box.x0 + 2.5, box.y1 - 2.3), label, fontname="hebo", fontsize=7, color=(1, 1, 1))

def _margin_notes(doc, notes: list[_Note], profile: list[str]) -> list[_Note]:
    """Размещает комментарии на поле справа напротив цитат. Возвращает те, что не поместились."""
    leftovers: list[_Note] = []
    by_page: dict[int, list[_Note]] = defaultdict(list)
    for n in notes:
        if n.page_index is None or doc[n.page_index].rotation:
            leftovers.append(n)
        else:
            by_page[n.page_index].append(n)
    if profile and doc.page_count and not doc[0].rotation:
        by_page.setdefault(0, [])

    for index in sorted(by_page):
        page = doc[index]
        content_width = page.rect.width
        _widen(page, _MARGIN)
        x0, x1, bottom = content_width + 10, content_width + _MARGIN - 10, page.rect.height - _PAGE_BOTTOM
        page.draw_line(fitz.Point(content_width, 0), fitz.Point(content_width, page.rect.height),
                       color=(0.82, 0.82, 0.82), width=0.5)
        cursor, markers = 16.0, []
        if index == 0 and profile:
            used = _put_html(page, fitz.Rect(x0, cursor, x1, bottom),
                             "<span class='meta'>" + "<br>".join(escape(p) for p in profile) + "</span>")
            cursor += (used or 0) + 10
        for n in sorted(by_page[index], key=lambda n: n.rect.y0 if n.rect else 0):
            color = _COLORS.get(n.finding["severity"], _COLORS["YELLOW"])
            if n.rect:
                _marker(page, n.rect, n.finding["number"], color, content_width, markers)
            placed = False
            for top in dict.fromkeys([max(cursor, n.rect.y0 - 2 if n.rect else cursor), cursor]):
                used = _put_html(page, fitz.Rect(x0 + 6, top, x1, bottom), _note_html(n.finding))
                if used is not None:
                    page.draw_rect(fitz.Rect(x0, top, x0 + 2.5, top + used), color=None, fill=color)
                    cursor = top + used + 8
                    placed = True
                    break
            if not placed:
                leftovers.append(n)
    return leftovers

def _appendix_page(doc) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=595, height=842)
    used = _put_html(page, fitz.Rect(50, 40, 545, 800),
                     "<b style='font-size: 11pt'>Замечания к документу</b><br><span class='meta'>"
                     "Не уместились на полях страниц или не привязаны к точному месту в тексте.</span>")
    return page, 40 + (used or 0) + 12

def _notes_appendix(doc, notes: list[_Note]) -> None:
    """Страницы в конце документа для замечаний, которые не поместились на полях."""
    page, cursor = _appendix_page(doc)
    for n in sorted(notes, key=lambda n: n.finding["number"] or 0):
        html = _note_html(n.finding, with_location=True)
        used = _put_html(page, fitz.Rect(58, cursor, 545, 802), html)
        if used is None:
            page, cursor = _appendix_page(doc)
            box = fitz.Rect(58, cursor, 545, 802)
            used = _put_html(page, box, html)
            if used is None:
                used = _put_html(page, box, html, scale_low=0.3) or box.height
        color = _COLORS.get(n.finding["severity"], _COLORS["YELLOW"])
        page.draw_rect(fitz.Rect(50, cursor, 52.5, cursor + used), color=None, fill=color)
        cursor += used + 10

def annotated_pdf(pdf_path: Path, findings: list[dict], target: Path, *, author: str | None = None,
                  company: str | None = None) -> Path:
    """Копия документа с подсветкой проблемных мест и комментариями на полях (для юриста)."""
    with PDF_LOCK, fitz.open(pdf_path) as doc:
        profile = ([f"Подготовил: {author}"] if author else []) + ([f"Компания: {company}"] if company else [])
        if profile:
            doc.set_metadata({**(doc.metadata or {}), "author": author or "", "subject": " · ".join(profile)})
        notes: list[_Note] = []
        for f in findings:
            if f["severity"] == "UNKNOWN":
                continue
            color = _COLORS.get(f["severity"], _COLORS["YELLOW"])
            note = _Note(f)
            for block in (f.get("highlights") or []) if f.get("quote_verified") else []:
                if not 1 <= block["page"] <= doc.page_count:
                    continue
                page = doc[block["page"] - 1]
                rects = [fitz.Rect(r) for r in block["rects"]]
                if not rects:
                    continue

                annot = page.add_highlight_annot(quads=[r.quad for r in rects])
                annot.set_colors(stroke=color)
                annot.update(opacity=0.45)
                if note.page_index is None:
                    note.page_index, note.rect = block["page"] - 1, rects[0]
            if note.page_index is None and f.get("page_number") and 1 <= f["page_number"] <= doc.page_count:
                note.page_index = f["page_number"] - 1
            notes.append(note)
        leftovers = _margin_notes(doc, notes, profile)
        if leftovers:
            _notes_appendix(doc, leftovers)

        doc.save(target, garbage=4, deflate=True)
    return target
