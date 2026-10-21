import codecs
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pymupdf
import pytest
from docx import Document as DocxDocument

from app.models import Analysis, Document, RiskFinding, RiskRule, User
from app.services import reports
from app.services.extraction import extract_pages
from app.services.quotes import locate_quote
from app.services.reports.data import ReportData, ReportDocument, ReportFinding, collect
from app.services.reports.docx_builder import BUILDERS


def _data(contract_pdf) -> ReportData:
    pages = [{"page_number": p.page_number, "words": p.words} for p in extract_pages(contract_pdf)]
    match = locate_quote(pages, "штраф в размере 0,1% от стоимости Контракта", (1, 1))

    def finding(number, severity, title, **kw):
        base = dict(number=number, severity=severity, category="Штрафы", title=title, short_description="Суть",
                    page_number=1, clause="6.2", exact_quote=match.text, comment="Обоснование",
                    counter_proposal="Новая редакция", legal_reference="ст. 34 44-ФЗ", review_status="NEW",
                    reviewer_comment=None, quote_verified=True, source="LLM", highlights=match.highlights)
        base.update(kw)
        return ReportFinding(**base)

    doc = ReportDocument(
        id=uuid.uuid4(), file_name="Проект контракта.pdf", relative_path="Проект контракта.pdf", status="COMPLETED",
        total_pages=2, is_scanned=False, law_type="44-FZ", risk_score=37, light="RED",
        preview_path=str(contract_pdf), error_message=None,
        findings=[
            finding(1, "RED", "Неограниченная ответственность"),
            finding(2, "YELLOW", "Срок поставки", exact_quote=None, highlights=[], page_number=2, clause="7.2"),
            finding(3, "LOW", "Подсудность", exact_quote=None, highlights=[], page_number=2, clause="11"),
            finding(None, "GREEN", "Срок оплаты", exact_quote=None, highlights=[], page_number=None, clause=None,
                    comment="Срок оплаты 7 рабочих дней"),
        ],
    )
    rule = RiskRule(id="r1", title="Неустойка", category="Штрафы", severity="RED", legal_reference="ст. 34")
    return ReportData(
        analysis_id=uuid.uuid4(), title="Проект контракта", original_filename="Проект контракта.pdf",
        created_at=datetime.now(), generated_at=datetime.now(), author="Кирилл Иванов", company="ООО Поставщик",
        rules_checked=3, documents=[doc], rules=[rule],
    )


@pytest.mark.parametrize("mode", ["brief", "detailed", "protocol"])
def test_docx_modes(contract_pdf, tmp_path, mode):
    data = _data(contract_pdf)
    path = BUILDERS[mode](data, tmp_path / f"{mode}.docx")
    docx = DocxDocument(path)
    text = "\n".join(p.text for p in docx.paragraphs)
    cells = "\n".join(c.text for t in docx.tables for r in t.rows for c in r.cells)
    if mode != "protocol":
        assert "Неограниченная ответственность" in cells + text
        assert "п. 6.2" in cells + text and "Низкий риск" in cells + text
    else:
        assert "ПРОТОКОЛ РАЗНОГЛАСИЙ" in text
        assert "Новая редакция" in cells and "штраф в размере 0,1%" in cells
    if mode == "detailed":
        assert "Срок оплаты 7 рабочих дней" in text  # пройденные проверки
    assert "Светофор рисков" not in text + cells
    assert text.rstrip().endswith("проверить специалисту.")


@pytest.mark.parametrize("mode", ["brief", "detailed"])
def test_summary_has_only_finding_counts(contract_pdf, tmp_path, mode):
    data = _data(contract_pdf)
    docx = DocxDocument(BUILDERS[mode](data, tmp_path / f"{mode}.docx"))
    summary = docx.tables[1].rows[0].cells
    assert [c.text for c in summary] == ["Критичных: 1", "Требуют внимания: 1, низкий риск: 1"]
    text = "\n".join(p.text for p in docx.paragraphs)
    cells = "\n".join(c.text for t in docx.tables for r in t.rows for c in r.cells)
    assert "Светофор" not in text + cells and "Индекс риска" not in text + cells
    assert text.rstrip().endswith("проверить специалисту.")
    assert "без LLM" not in text  # все замечания найдены LLM


@pytest.mark.parametrize("mode", ["brief", "detailed"])
def test_heuristic_note_is_written_once_at_the_top(contract_pdf, tmp_path, mode):
    data = _data(contract_pdf)
    for f in data.documents[0].findings:
        f.source = "HEURISTIC"
    paragraphs = [p.text for p in DocxDocument(BUILDERS[mode](data, tmp_path / f"{mode}.docx")).paragraphs]
    assert "\n".join(paragraphs).count("без LLM") == 1
    note = next(i for i, p in enumerate(paragraphs) if "без LLM" in p)
    first_issue = paragraphs.index("Замечания") if mode == "brief" else next(
        i for i, p in enumerate(paragraphs) if p.startswith("№1."))
    assert note < first_issue

    data.documents[0].findings[0].source = "LLM"
    text = "\n".join(p.text for p in DocxDocument(BUILDERS[mode](data, tmp_path / f"{mode}-mixed.docx")).paragraphs)
    assert "Замечания №2, №3 найдены без LLM" in text


def test_json_and_annotated(contract_pdf):
    data = _data(contract_pdf)
    report = reports.generate(data, "brief", "json")
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert payload["traffic_light"] == "RED" and len(payload["documents"][0]["findings"]) == 3

    table = reports.generate(data, "brief", "csv").path.read_bytes()
    assert table.startswith(codecs.BOM_UTF8)  # BOM для Excel
    rows = table.decode("utf-8-sig").splitlines()
    assert any('"Критические замечания";"Неограниченная ответственность"' in r for r in rows)
    assert not any("Срок оплаты" in r for r in rows)  # краткий режим — без пройденных проверок

    annotated = reports.generate(data, "annotated", "pdf")
    with pymupdf.open(contract_pdf) as source:
        width, pages = source[0].rect.width, source.page_count
    with pymupdf.open(annotated.path) as pdf:
        page = pdf[0]
        types = [a.type[1] for a in page.annots()]
        # Всплывающих заметок нет: Chrome показывает их без кириллицы. Комментарии напечатаны на поле справа.
        assert "Highlight" in types and "Text" not in types and "Popup" not in types
        # и у подсветки нет текста заметки — Chrome показывал бы его при наведении
        assert all(not a.info["content"] and not a.info["title"] for a in page.annots())
        assert page.rect.width > width
        margin = page.get_text("text", clip=pymupdf.Rect(width, 0, page.rect.width, page.rect.height))
        assert "Неограниченная ответственность" in margin and "Критично" in margin
        assert "Подготовил: Кирилл Иванов" in margin
        quote = next(w for w in page.get_text("words") if w[4] == "штраф")
        assert quote[2] < width  # содержимое страницы не сдвинулось
        # замечание без точной цитаты — на поле своей страницы; всё уместилось, лишних страниц нет
        assert "Срок поставки" in pdf[1].get_text() and pdf.page_count == pages

    with pytest.raises(reports.ReportError):
        reports.generate(data, "annotated", "docx")


def test_annotated_pdf_moves_notes_without_place_to_appendix(contract_pdf, tmp_path):
    from app.services.pdf_tools import annotated_pdf

    long_comment = "Очень длинное обоснование замечания. " * 60
    findings = [dict(number=n, severity="YELLOW", title=f"Замечание {n}", comment=long_comment, counter_proposal=None,
                     quote_verified=False, highlights=[], page_number=1, clause="1") for n in range(1, 4)]
    findings.append(dict(number=4, severity="RED", title="Без страницы", comment="Обоснование", counter_proposal=None,
                         quote_verified=False, highlights=[], page_number=None, clause=None))
    with pymupdf.open(contract_pdf) as source:
        pages = source.page_count
    with pymupdf.open(annotated_pdf(contract_pdf, findings, tmp_path / "a.pdf")) as pdf:
        appendix = "\n".join(pdf[i].get_text() for i in range(pages, pdf.page_count))
        assert pdf.page_count > pages and "Замечания к документу" in appendix
        assert "Без страницы" in appendix and "стр. 1" in appendix  # у не уместившихся на поле — место в тексте
        everywhere = "\n".join(p.get_text() for p in pdf)
        assert all(f"Замечание {n}" in everywhere for n in range(1, 4))


def test_csv_formula_injection_is_neutralized():
    from app.services.reports import csv_cell

    assert csv_cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert csv_cell("  +7 (999)") == "'  +7 (999)"
    assert csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert csv_cell("\ufeff=1+1") == "'\ufeff=1+1"
    assert csv_cell("Срок оплаты — 30 дней") == "Срок оплаты — 30 дней"
    assert csv_cell(5) == 5


def _collected_report(status="COMPLETED", include_dismissed=False, with_findings=False):
    analysis = Analysis(id=uuid.uuid4(), title="Contract", original_filename="contract.pdf",
                        created_at=datetime.now())
    document = Document(id=uuid.uuid4(), analysis_id=analysis.id, file_name="contract.pdf", status=status,
                        total_pages=1, is_scanned=False, risk_score=99)
    rule = RiskRule(id="r1", title="Неустойка", category="Штрафы", severity="RED")
    finding = RiskFinding(id=uuid.uuid4(), document_id=document.id, rule_id=rule.id, severity="RED",
                          title="Неустойка", comment="Отменённый риск", review_status="DISMISSED",
                          sort_index=0, quote_verified=False, source="HEURISTIC")
    db = MagicMock()
    db.scalars.side_effect = [[document], [finding] if with_findings else [], [rule]]
    return collect(db, analysis, User(full_name="Analyst"), include_dismissed=include_dismissed)


@pytest.mark.parametrize("status", ["FAILED", "COMPLETED"])
def test_report_without_completed_checks_has_unknown_assessment(status):
    data = _collected_report(status)

    assert data.light == data.documents[0].light == "UNKNOWN"
    assert data.risk_score is None and data.documents[0].risk_score is None
    assert data.rules_checked == data.documents[0].rules_checked == 0


@pytest.mark.parametrize("include_dismissed", [False, True])
def test_report_counts_executed_rules_even_when_all_findings_are_dismissed(include_dismissed):
    data = _collected_report(include_dismissed=include_dismissed, with_findings=True)

    assert data.rules_checked == data.documents[0].rules_checked == 1
    assert data.light == data.documents[0].light == "GREEN"
    assert data.risk_score == data.documents[0].risk_score == 0
    assert len(data.documents[0].findings) == int(include_dismissed)


@pytest.mark.parametrize("mode", ["brief", "detailed", "protocol"])
@pytest.mark.parametrize("status", ["FAILED", "COMPLETED"])
def test_unassessed_docx_never_claims_no_risks_or_no_disagreements(tmp_path, mode, status):
    data = _collected_report(status)
    path = BUILDERS[mode](data, tmp_path / f"{mode}-{status}.docx")
    docx = DocxDocument(path)
    text = "\n".join(p.text for p in docx.paragraphs)
    cells = "\n".join(c.text for t in docx.tables for r in t.rows for c in r.cells)
    all_text = text + cells

    assert "Оценка рисков недоступна" in all_text
    assert "Зелёный" not in all_text
    assert "Замечаний нет." not in all_text
    assert "Разногласий по проверенным правилам не выявлено." not in all_text
    assert "None из 100" not in all_text


def test_unknown_assessment_is_preserved_in_json():
    data = _collected_report("FAILED")
    report = reports.generate(data, "brief", "json")
    payload = json.loads(report.path.read_text(encoding="utf-8"))

    assert payload["traffic_light"] == payload["documents"][0]["traffic_light"] == "UNKNOWN"
    assert payload["risk_score"] is None and payload["documents"][0]["risk_score"] is None


def test_incomplete_package_does_not_inherit_green_from_its_completed_document():
    completed = _collected_report(with_findings=True)
    failed = _collected_report("FAILED")
    completed.documents.extend(failed.documents)

    assert completed.light == "UNKNOWN"
    assert completed.risk_score is None


@pytest.mark.parametrize("mode", ["brief", "detailed", "protocol"])
def test_unknown_finding_is_not_reported_as_confirmed_disagreement(contract_pdf, tmp_path, mode):
    data = _data(contract_pdf)
    unknown = data.documents[0].findings[0]
    unknown.severity = "UNKNOWN"
    unknown.title = "Неподтверждённый вывод"
    unknown.comment = "Цитата не подтверждена"
    unknown.counter_proposal = "Не отправлять как правку"
    unknown.quote_verified = False
    data.documents[0].findings = [unknown]
    data.documents[0].light = "UNKNOWN"
    data.documents[0].risk_score = None

    path = BUILDERS[mode](data, tmp_path / f"unknown-{mode}.docx")
    document = DocxDocument(path)
    text = "\n".join(p.text for p in document.paragraphs)
    cells = "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)

    assert data.light == "UNKNOWN" and data.risk_score is None
    assert "Замечаний нет." not in text
    assert "Разногласий по проверенным правилам не выявлено." not in text
    if mode == "protocol":
        assert "Не отправлять как правку" not in cells
    else:
        assert "Недостаточно данных" in cells + text


def test_unknown_finding_cannot_be_exported_as_a_clean_annotated_pdf(contract_pdf):
    data = _data(contract_pdf)
    data.documents[0].findings = data.documents[0].findings[:1]
    data.documents[0].findings[0].severity = "UNKNOWN"
    data.documents[0].findings[0].quote_verified = False
    with pytest.raises(reports.ReportError, match="недостаточно данных"):
        reports.generate(data, "annotated", "pdf")
