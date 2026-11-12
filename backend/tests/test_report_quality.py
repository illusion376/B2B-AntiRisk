"""Качество не теряется при экспорте, в том числе у документов без замечаний."""
import csv
import json
import uuid
from datetime import datetime
from pathlib import Path

import pymupdf
import pytest
from docx import Document as DocxDocument

from app.schemas import DocumentQuality
from app.services import reports
from app.services.reports.data import ReportData, ReportDocument
from app.services.reports.docx_builder import BUILDERS
from app.services.reports.quality import duration_label, quality_page_rows, quality_rows


def _quality(status="low", **changes):
    values = dict(
        status=status, confidence_threshold=80, total_pages=2, ocr_pages=1, native_pages=1,
        ocr_percent=50, native_percent=50, measured_ocr_pages=1, confidence=32.5,
        review_pages=[dict(page=2, status="low", confidence=32.5, reason="low_confidence",
                           warning="Уверенность OCR ниже порога. Результат требует ручной проверки")],
        manual_review_required=True, warning="Результат требует ручной проверки",
        processing_ms=120_001, processing_kind="full", sla_ms=120_000, sla_status="exceeded",
    )
    if status == "native":
        values.update(confidence=None, ocr_pages=0, native_pages=2, ocr_percent=0, native_percent=100,
                      measured_ocr_pages=0, review_pages=[], manual_review_required=False, warning=None)
    elif status == "unknown":
        values.update(confidence=None, measured_ocr_pages=0,
                      review_pages=[dict(page=2, status="unknown", confidence=None, reason="ocr_failed",
                                         warning="Не удалось распознать страницу. Результат требует ручной проверки")])
    values.update(changes)
    return DocumentQuality(**values)


def _data(qualities, preview_path=None):
    return ReportData(
        analysis_id=uuid.uuid4(), title="Проверка пакета", original_filename="Документы.zip",
        created_at=datetime.now(), generated_at=datetime.now(), author="Юрист", company="Заказчик",
        rules_checked=1, rules=[], documents=[
            ReportDocument(
                id=uuid.uuid4(), file_name=f"Документ {index + 1}.pdf", relative_path=f"Пакет/Документ {index + 1}.pdf",
                status="COMPLETED", total_pages=2, is_scanned=quality.ocr_pages > 0, law_type=None,
                risk_score=0, light="GREEN", preview_path=str(preview_path) if preview_path else None,
                error_message=None, rules_checked=1, quality=quality,
            )
            for index, quality in enumerate(qualities)
        ],
    )


def _docx_text(path):
    doc = DocxDocument(path)
    return "\n".join([paragraph.text for paragraph in doc.paragraphs]
                     + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])


@pytest.mark.parametrize("mode", BUILDERS)
def test_docx_quality_section_keeps_all_documents_even_without_findings(tmp_path, mode):
    data = _data([_quality(), _quality("native"), _quality("unknown")])
    text = _docx_text(BUILDERS[mode](data, tmp_path / f"{mode}.docx"))

    assert text.count("Качество проверки документа") == 3
    assert all(document.relative_path in text for document in data.documents)
    assert "Результат требует ручной проверки" in text
    assert "32,5%" in text and "Страница 2" in text
    assert "Не удалось распознать страницу" in text
    assert "Текстовый слой — уверенность OCR не измерялась" in text
    assert "Сканы / OCR: 1 из 2 (50%)" in text
    assert "Текстовый слой: 1 из 2 (50%)" in text
    assert "Превышен: лимит 2 мин, превышение 1 мс" in text


@pytest.mark.parametrize("mode", ["brief", "detailed", "protocol"])
def test_json_preserves_machine_readable_quality_without_findings(mode):
    quality = _quality()
    data = _data([quality, _quality("native")])
    report = reports.generate(data, mode, "json")
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert payload["documents"][0]["quality"] == quality.model_dump(mode="json")
    assert payload["documents"][0]["findings"] == []
    assert payload["documents"][1]["quality"]["confidence"] is None
    assert payload["documents"][1]["quality"]["status"] == "native"


@pytest.mark.parametrize("mode", ["brief", "detailed"])
def test_csv_quality_section_includes_empty_documents_and_neutralizes_names(mode):
    data = _data([_quality(), _quality("unknown")])
    data.documents[1].relative_path = "=HYPERLINK(\"bad\")"
    path = reports.generate(data, mode, "csv").path
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream, delimiter=";"))
    title_index = rows.index(["Качество проверки документа"])
    quality = rows[title_index + 2:]
    assert any(row[0] == data.documents[0].relative_path and "32,5%" in row[2]
               for row in quality if len(row) == 3)
    assert any(row[0] == "'=HYPERLINK(\"bad\")" and "Не удалось распознать страницу" in row[2]
               for row in quality if len(row) == 3)
    assert any(row[1] == "Норматив времени" and "Превышен" in row[2]
               for row in quality if len(row) == 3)


def test_annotated_pdf_marks_low_page_and_appends_quality_without_renumbering(contract_pdf):
    data = _data([_quality()], contract_pdf)
    path = reports.generate(data, "annotated", "pdf").path
    with pymupdf.open(contract_pdf) as source, pymupdf.open(path) as result:
        assert result.page_count > source.page_count
        assert "Срок поставки" in result[1].get_text()
        margin = result[1].get_text(clip=pymupdf.Rect(source[1].rect.width, 0,
                                                   result[1].rect.width, result[1].rect.height))
        assert "Качество распознавания" in margin
        assert "Результат требует ручной проверки" in " ".join(margin.split())
        appendix = " ".join(result[index].get_text() for index in range(source.page_count, result.page_count))
        assert "Качество проверки документа" in appendix and "Страница 2" in appendix
        assert "Превышен" in appendix and "32,5%" in appendix


def test_annotated_pdf_keeps_rotation_when_marking_bad_scan(contract_pdf, tmp_path):
    rotated = tmp_path / "rotated.pdf"
    with pymupdf.open(contract_pdf) as source:
        source[1].set_rotation(90)
        source.save(rotated)
    data = _data([_quality()], rotated)
    with pymupdf.open(reports.generate(data, "annotated", "pdf").path) as result:
        assert result[1].rotation == 90
        text = " ".join(result[1].get_text().split())
        assert "Срок поставки" in text
        assert "Результат требует ручной проверки" in text


@pytest.mark.parametrize("quality,required,forbidden", [
    (_quality("native", processing_ms=120_000, sla_status="within"), "В пределах норматива", "Превышен"),
    (_quality(sla_ms=None, sla_status="not_configured"), "Норматив не задан", "В пределах норматива"),
    (_quality(processing_ms=None, sla_status="not_measured"), "Не измерено", "В пределах норматива"),
    (_quality(processing_kind="reanalysis", sla_status="not_applicable"), "неприменим к повторной проверке", "В пределах норматива"),
    (_quality(sla_status="not_applicable"), "проверка не завершена полностью", "повторной проверке"),
    (DocumentQuality(manual_review_required=True), "Результат требует ручной проверки", "соответствует порогу"),
])
def test_report_does_not_invent_quality_or_sla_success(quality, required, forbidden):
    text = "\n".join(value for _, value in quality_rows(quality))
    assert required in text
    assert forbidden not in text


def test_report_percentages_use_tenths_without_changing_numeric_quality():
    quality = _quality(
        confidence=92.2857, confidence_threshold=95.5555,
        total_pages=3, native_pages=2, ocr_percent=33.3333, native_percent=66.6667,
        review_pages=[dict(page=2, status="low", confidence=92.2857, reason="low_confidence",
                           warning="Низкая уверенность OCR. Результат требует ручной проверки")],
    )
    before = quality.model_dump(mode="json")

    rows = dict(quality_rows(quality))
    assert "92,3%" in rows["Оценка распознавания"]
    assert rows["Порог уверенности OCR"] == "95,6%"
    assert rows["Источник текста"] == "Сканы / OCR: 1 из 3 (33,3%). Текстовый слой: 2 из 3 (66,7%)"
    assert "Уверенность OCR: 92,3%" in quality_page_rows(quality)[0][1]
    assert quality.model_dump(mode="json") == before


@pytest.mark.parametrize("milliseconds,expected", [(0, "0 мс"), (1, "1 мс"), (1000, "1 с"),
                                                    (60_000, "1 мин"), (120_001, "2 мин 0,001 с"),
                                                    (None, "Не измерено")])
def test_report_duration_preserves_zero_and_small_sla_excess(milliseconds, expected):
    assert duration_label(milliseconds) == expected


@pytest.mark.parametrize("mode", BUILDERS)
def test_pdf_report_contains_same_quality_section(contract_pdf, tmp_path, mode):
    import shutil

    from app.config import settings

    if not shutil.which(settings.soffice_bin):
        pytest.skip("LibreOffice не установлен")
    data = _data([_quality()], contract_pdf)
    path = reports.generate(data, mode, "pdf").path
    with pymupdf.open(path) as document:
        text = " ".join(page.get_text() for page in document)
    assert "Качество проверки документа" in text
    assert "Результат требует ручной проверки" in text
    assert "Превышен" in text
