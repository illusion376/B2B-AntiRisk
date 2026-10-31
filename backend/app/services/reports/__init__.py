"""Генерация отчётов на бэкенде в нескольких режимах и форматах."""
import csv
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.schemas import ReportMode
from app.services import pdf_tools, storage
from app.services.reports.data import ReportData
from app.services.reports.docx_builder import BUILDERS
from app.vocab import REVIEW_LABELS, SEVERITY_GROUP_LABELS

MODES: list[ReportMode] = [
    ReportMode(id="brief", title="Краткий",
               description="Количество замечаний по уровням и таблица замечаний: уровень, суть, пункт, страница",
               formats=["docx", "pdf", "csv", "json"]),
    ReportMode(id="detailed", title="Подробный",
               description="Каждое замечание с цитатой, обоснованием, рекомендацией и нормой права; "
                           "список пройденных проверок и применённых правил",
               formats=["docx", "pdf", "csv", "json"]),
    ReportMode(id="protocol", title="Протокол разногласий",
               description="Таблица «редакция заказчика → предлагаемая редакция → обоснование» для направления заказчику",
               formats=["docx", "pdf", "json"]),
    ReportMode(id="annotated", title="Документ с пометками",
               description="Исходный документ в PDF с подсветкой проблемных мест и комментариями на полях",
               formats=["pdf"]),
]
MODE_IDS = {m.id: m for m in MODES}
MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "json": "application/json",
    "csv": "text/csv; charset=utf-8",
}

class ReportError(ValueError):
    pass

@dataclass
class ReportFile:
    path: Path
    filename: str
    media_type: str

def _slug(text: str) -> str:
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")[:80] or "report"

def _docx_to_pdf(docx_path: Path) -> Path:
    soffice = shutil.which(settings.soffice_bin)
    if not soffice:
        raise ReportError("Экспорт в PDF недоступен: LibreOffice не установлен. Выберите формат DOCX")
    with tempfile.TemporaryDirectory() as tmp:
        profile = (Path(tmp) / "profile").as_uri()
        subprocess.run(
            [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
            capture_output=True, timeout=settings.convert_timeout_s, check=False,
        )
    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise ReportError("Не удалось сконвертировать отчёт в PDF")
    return pdf_path

def _json_payload(data: ReportData, mode: str) -> dict:
    def finding(f):
        return {k: v for k, v in f.__dict__.items() if k != "highlights"} | {"highlights": f.highlights}

    payload = {
        "mode": mode,
        "analysis_id": str(data.analysis_id),
        "title": data.title,
        "original_filename": data.original_filename,
        "generated_at": data.generated_at.isoformat(),
        "author": data.author,
        "company": data.company,
        "traffic_light": data.light,
        "risk_score": data.risk_score,
        "rules_checked": data.rules_checked,
        "documents": [
            {
                "id": str(d.id), "file_name": d.file_name, "relative_path": d.relative_path, "status": d.status,
                "total_pages": d.total_pages, "law_type": d.law_type, "risk_score": d.risk_score,
                "traffic_light": d.light,
                "findings": [finding(f) for f in (d.findings if mode == "detailed" else d.issues)],
            }
            for d in data.documents
        ],
    }
    if data.target_document:
        payload["target_document"] = {
            "id": str(data.target_document.id),
            "file_name": data.target_document.file_name,
            "relative_path": data.target_document.relative_path,
        }
    return payload

_FORMULA_LIKE = re.compile(r"^(?:[\s\x00-\x1f\ufeff]*[=+\-@]|[\t\r\n])")

def csv_cell(value):
    """Кавычки CSV не мешают Excel выполнить формулу: текст документа вида «=HYPERLINK(...)»
    экранируем апострофом — так же, как frontend/lib/report.ts."""
    if isinstance(value, str) and _FORMULA_LIKE.match(value):
        return "'" + value
    return value

class _SafeCsvWriter:
    def __init__(self, f):
        self._writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)

    def writerow(self, row: list) -> None:
        self._writer.writerow([csv_cell(v) for v in row])

def _write_csv(data: ReportData, mode: str, path: Path) -> None:
    """Таблица как у CSV-отчёта фронтенда: UTF-8 с BOM и «;» — открывается в Excel без настройки."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = _SafeCsvWriter(f)
        if data.target_document:
            writer.writerow(["Проверенный файл", data.target_document.relative_path or data.target_document.file_name])
            if (
                data.original_filename.lower().endswith((".zip", ".tar", ".gz", ".7z", ".rar"))
                or data.target_document.file_name != data.original_filename
            ):
                writer.writerow(["Исходный архив", data.original_filename])
        else:
            is_archive = bool(
                data.original_filename.lower().endswith((".zip", ".tar", ".gz", ".7z", ".rar"))
                or len(data.documents) > 1
            )
            writer.writerow(["Исходный архив" if is_archive else "Исходный файл", data.original_filename])
            if len(data.documents) > 1:
                writer.writerow(["Документов в отчёте", len(data.documents)])
        writer.writerow(["Режим", MODE_IDS[mode].title])
        writer.writerow(["Подготовил", data.author or "—"])
        writer.writerow(["Компания", data.company or "—"])
        writer.writerow(["Индекс риска", data.risk_score])
        writer.writerow(["Проверено правил", data.rules_checked])
        writer.writerow([])
        writer.writerow(["Документ", "№", "Уровень", "Замечание", "Описание", "Пункт", "Страница", "Цитата",
                         "Рекомендация", "Норма", "Статус"])
        for doc in data.documents:
            for item in (doc.findings if mode == "detailed" else doc.issues):
                writer.writerow([
                    doc.relative_path or doc.file_name, item.number or "",
                    SEVERITY_GROUP_LABELS.get(item.severity, item.severity), item.title,
                    item.short_description or "", item.clause or "", item.page_number or "",
                    item.exact_quote or "", item.counter_proposal or "", item.legal_reference or "",
                    REVIEW_LABELS.get(item.review_status, item.review_status),
                ])

def generate(data: ReportData, mode: str, fmt: str) -> ReportFile:
    if mode not in MODE_IDS:
        raise ReportError(f"Неизвестный режим отчёта: {mode}")
    if fmt not in MODE_IDS[mode].formats:
        raise ReportError(f"Режим «{MODE_IDS[mode].title}» поддерживает форматы: {', '.join(MODE_IDS[mode].formats)}")
    if not data.documents:
        raise ReportError("Нет документов для отчёта")

    out_dir = storage.subdir(data.analysis_id, "reports")
    if data.target_document:
        doc_stem = Path(data.target_document.file_name).stem
        base = f"{_slug(doc_stem)}_{mode}"
    else:
        base = f"{_slug(data.title)}_{mode}"
    target = out_dir / f"{uuid.uuid4().hex}"

    if mode == "annotated":
        if len(data.documents) != 1:
            raise ReportError("Документ с пометками формируется для одного документа — укажите document_id")
        doc = data.documents[0]
        if not doc.preview_path:
            raise ReportError("Документ ещё не обработан")
        if any(f.severity == "UNKNOWN" and f.review_status != "DISMISSED" for f in doc.findings):
            raise ReportError("PDF с пометками недоступен: по части проверок недостаточно данных. "
                              "Скачайте подробный отчёт — он содержит причины неполной оценки.")
        findings = [f.__dict__ for f in doc.issues]
        path = pdf_tools.annotated_pdf(Path(doc.preview_path), findings, target.with_suffix(".pdf"),
                                       author=data.author, company=data.company)
        return ReportFile(path, f"{_slug(Path(doc.file_name).stem)}_с_пометками.pdf", MEDIA_TYPES["pdf"])

    if fmt == "csv":
        path = target.with_suffix(".csv")
        _write_csv(data, mode, path)
        return ReportFile(path, f"{base}.csv", MEDIA_TYPES["csv"])

    if fmt == "json":
        path = target.with_suffix(".json")
        path.write_text(json.dumps(_json_payload(data, mode), ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
        return ReportFile(path, f"{base}.json", MEDIA_TYPES["json"])

    docx_path = BUILDERS[mode](data, target.with_suffix(".docx"))
    if fmt == "pdf":
        return ReportFile(_docx_to_pdf(docx_path), f"{base}.pdf", MEDIA_TYPES["pdf"])
    return ReportFile(docx_path, f"{base}.docx", MEDIA_TYPES["docx"])
