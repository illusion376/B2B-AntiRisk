"""OCR сканов и подготовка форматов: штамп ЭП на скане, родное разрешение, TXT в cp1251."""
import io
import shutil

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services import extraction
from app.services.converter import decode_text, to_pdf
from tests.conftest import cyrillic_font

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="нет tesseract")
needs_soffice = pytest.mark.skipif(shutil.which("soffice") is None, reason="нет LibreOffice")

TEXT = "6.2. Поставщик уплачивает Заказчику штраф в размере 10 процентов цены Контракта."


def _scan_pdf(tmp_path, dpi=200, stamp: str | None = None):
    """PDF-страница A4, на которой только картинка-скан (без текстового слоя), опционально со штампом ЭП."""
    font_path = cyrillic_font()
    if font_path is None:
        pytest.skip("Нет шрифта с кириллицей")
    w, h = int(8.27 * dpi), int(11.69 * dpi)
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, int(dpi * 0.15))
    for i, line in enumerate([TEXT[:42], TEXT[42:]]):
        draw.text((int(dpi * 0.8), int(dpi * (1 + i * 0.3))), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    if stamp:
        page.insert_text((40, 830), stamp, fontsize=7, fontname="cyr", fontfile=font_path)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    return path, (w, h)


def test_scan_rendered_at_native_resolution(tmp_path):
    path, size = _scan_pdf(tmp_path, dpi=200)
    with pymupdf.open(path) as doc:
        assert extraction._scan_dpi(doc[0]) == 200
        image = extraction._render(doc[0])
    # не растягиваем до 300 DPI: интерполяция портит буквы
    assert abs(image.width - size[0]) <= 2 and abs(image.height - size[1]) <= 2


def test_stamp_on_scan_triggers_ocr(tmp_path):
    stamp = "Документ подписан электронной подписью. Сертификат 01DA4F7E, владелец Иванов И. И."
    path, _ = _scan_pdf(tmp_path, stamp=stamp)
    with pymupdf.open(path) as doc:
        page = doc[0]
        native = extraction._native_page(page, 1)
        assert len(native.text) > extraction.settings.ocr_min_text_chars  # штамп — это текстовый слой
        assert extraction._needs_ocr(page, native)


def test_text_page_is_not_ocred(contract_pdf):
    with pymupdf.open(contract_pdf) as doc:
        assert not extraction._needs_ocr(doc[0], extraction._native_page(doc[0], 1))


def test_junk_text_layer():
    assert extraction._is_junk_text("\x01\x01\x01 \x01\x01  ab")
    assert not extraction._is_junk_text("1 | 350,5 | 701 | шт | 2 | 701,00 руб. №5")


@needs_tesseract
def test_scan_with_stamp_is_recognized(tmp_path):
    path, _ = _scan_pdf(tmp_path, stamp="Документ подписан электронной подписью. Сертификат 01DA4F7E")
    page = extraction.extract_pages(path)[0]
    assert page.is_ocr
    assert "штраф" in page.text and "Контракта" in page.text


def test_decode_text_cp1251_and_utf8():
    assert decode_text(TEXT.encode("cp1251")) == TEXT
    assert decode_text(TEXT.encode("utf-8")) == TEXT
    assert decode_text("﻿".encode("utf-8") + TEXT.encode("utf-8")) == TEXT


@needs_soffice
def test_txt_cp1251_converted_without_garbage(tmp_path):
    src = tmp_path / "old.txt"
    src.write_bytes(TEXT.encode("cp1251"))
    with pymupdf.open(to_pdf(src, tmp_path / "old.pdf")) as doc:
        text = " ".join(doc[0].get_text().split())
    assert "Поставщик уплачивает Заказчику штраф" in text
