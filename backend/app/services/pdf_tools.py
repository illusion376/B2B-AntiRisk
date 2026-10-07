"""Операции PyMuPDF в процессе API. MuPDF не потокобезопасен, а FastAPI выполняет sync-эндпоинты
в пуле потоков, поэтому все вызовы сериализуются через общий lock."""
import threading
import uuid
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


def annotated_pdf(pdf_path: Path, findings: list[dict], target: Path) -> Path:
    """Копия документа с подсветкой проблемных мест и всплывающими комментариями (для юриста)."""
    with PDF_LOCK, fitz.open(pdf_path) as doc:
        for f in findings:
            color = _COLORS.get(f["severity"], _COLORS["YELLOW"])
            note = (
                f"№{f['number']} {_SEVERITY_LABEL.get(f['severity'], '')}: {f['title']}\n\n{f['comment']}"
                + (f"\n\nРекомендация: {f['counter_proposal']}" if f.get("counter_proposal") else "")
            )
            placed = False
            for block in f.get("highlights") or []:
                if not 1 <= block["page"] <= doc.page_count:
                    continue
                page = doc[block["page"] - 1]
                rects = [fitz.Rect(r) for r in block["rects"]]
                if not rects:
                    continue
                annot = page.add_highlight_annot(quads=[r.quad for r in rects])
                annot.set_colors(stroke=color)
                annot.set_info(title="Светофор рисков", content=note)
                annot.update(opacity=0.45)
                if not placed:
                    # Метка-комментарий на полях напротив первой строки цитаты
                    anchor = fitz.Point(max(page.rect.x0 + 4, rects[0].x0 - 22), rects[0].y0)
                    text_annot = page.add_text_annot(anchor, note, icon="Comment")
                    text_annot.set_colors(stroke=color)
                    text_annot.set_info(title=f"Замечание №{f['number']}")
                    text_annot.update()
                    placed = True
            if not placed and f.get("page_number") and 1 <= f["page_number"] <= doc.page_count:
                page = doc[f["page_number"] - 1]
                text_annot = page.add_text_annot(fitz.Point(page.rect.x0 + 10, page.rect.y0 + 20), note, icon="Note")
                text_annot.set_colors(stroke=color)
                text_annot.set_info(title=f"Замечание №{f['number']}")
                text_annot.update()
        doc.save(target, garbage=3, deflate=True)
    return target
