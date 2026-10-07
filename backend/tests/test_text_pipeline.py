"""Извлечение текста -> структура -> поиск цитат на синтетическом договоре."""
from app.services.extraction import extract_pages
from app.services.quotes import locate_quote
from app.services.search import search_pages
from app.services.structure import build_chunks, build_outline, detect_law_type, split_segments


def _pages_dicts(pages):
    return [{"page_number": p.page_number, "words": p.words} for p in pages]


def test_extract_and_structure(contract_pdf):
    pages = extract_pages(contract_pdf)
    assert len(pages) == 2 and not any(p.is_ocr for p in pages)
    assert "Поставщик уплачивает Заказчику штраф" in pages[0].text

    segments = split_segments(pages)
    clauses = [s.clause for s in segments if s.clause]
    assert clauses == ["6.1", "6.2", "7.1", "7.2"]
    # Дата 31.12.2025 не должна приниматься за номер пункта
    assert all(not c.startswith("31") for c in clauses)

    outline = build_outline(segments)
    assert [s["title"] for s in outline] == ["6. Ответственность сторон", "7. Срок действия контракта"]
    assert [c["clause"] for c in outline[0]["clauses"]] == ["6.1", "6.2"]
    assert outline[1]["page"] == 2

    chunks = build_chunks(segments)
    assert chunks and all(c.content for c in chunks)
    joined = " ".join(c.content for c in chunks)
    assert "ограниченной общей суммой" in joined  # перенос «огра-/ниченной» склеен
    assert detect_law_type(joined) == "44-FZ"


def test_locate_quote_exact_fuzzy_and_hyphenated(contract_pdf):
    pages = _pages_dicts(extract_pages(contract_pdf))

    exact = locate_quote(pages, "штраф в размере 0,1% от стоимости Контракта", (1, 1))
    assert exact.verified and exact.page_number == 1 and exact.clause == "6.2"
    assert exact.highlights and exact.highlights[0]["page"] == 1
    assert len(exact.highlights[0]["rects"]) == 2  # цитата на двух строках -> два прямоугольника

    # LLM склеила перенос и поменяла кавычки/регистр — всё равно находим
    hyphen = locate_quote(pages, "НЕ ОГРАНИЧЕННОЙ общей суммой «Контракта»", (1, 1))
    assert hyphen.verified and hyphen.clause == "6.2"

    fuzzy = locate_quote(pages, "Срок поставки товара составляет 60 календарных дн.", (2, 2))
    assert fuzzy.verified and fuzzy.page_number == 2 and fuzzy.clause == "7.2"
    assert "60 календарных дней" in fuzzy.text

    # Цитата начинается с заголовка раздела 7 — пункт не должен «утечь» из раздела 6
    heading = locate_quote(pages, "СРОК ДЕЙСТВИЯ КОНТРАКТА 7.1. Настоящий Контракт вступает в силу", (2, 2))
    assert heading.verified and heading.clause == "7.1"

    missing = locate_quote(pages, "Заказчик вправе изменить цену в одностороннем порядке", (1, 2))
    assert not missing.verified


def test_search(contract_pdf):
    pages = _pages_dicts(extract_pages(contract_pdf))
    hits, total = search_pages(pages, "контракт", limit=10)
    assert total >= 3
    assert {h.page for h in hits} == {1, 2}
    assert all(h.highlights for h in hits)


def test_page_sections_for_html_viewer(contract_pdf):
    from app.services.structure import page_sections

    pages = [(p.page_number, p.text) for p in extract_pages(contract_pdf)]
    first = page_sections(pages, 1)
    assert first[0]["title"] == "6. ОТВЕТСТВЕННОСТЬ СТОРОН"
    assert [p["clause"] for p in first[0]["paragraphs"]] == ["6.1", "6.2"]
    # Строки пункта склеены в абзац, перенос «огра-/ниченной» убран
    assert "не ограниченной общей суммой Контракта." in first[0]["paragraphs"][1]["text"]

    second = page_sections(pages, 2)
    assert second[0]["title"] == "7. СРОК ДЕЙСТВИЯ КОНТРАКТА"
    assert [p["clause"] for p in second[0]["paragraphs"]] == ["7.1", "7.2"]
