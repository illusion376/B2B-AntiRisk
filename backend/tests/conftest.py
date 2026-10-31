import os
from pathlib import Path

import pytest

os.environ.setdefault("STORAGE_DIR", str(Path(__file__).parent / ".storage"))
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("EMBEDDING_BASE_URL", "")

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "C:/Windows/Fonts/times.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

CONTRACT_PAGES = [
    [
        "6. ОТВЕТСТВЕННОСТЬ СТОРОН",
        "6.1. Стороны несут ответственность за неисполнение обязательств",
        "по настоящему Контракту в соответствии с законодательством.",
        "6.2. Поставщик уплачивает Заказчику штраф в размере 0,1% от стоимости",
        "Контракта за каждый день просрочки исполнения обязательств, но не огра-",
        "ниченной общей суммой Контракта.",
    ],
    [
        "7. СРОК ДЕЙСТВИЯ КОНТРАКТА",
        "7.1. Настоящий Контракт вступает в силу с даты его подписания",
        "и действует до 31.12.2025 в соответствии с 44-ФЗ.",
        "7.2. Срок поставки Товара составляет 60 календарных дней.",
    ],
]


def cyrillic_font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


@pytest.fixture
def contract_pdf(tmp_path) -> Path:
    import pymupdf

    font = cyrillic_font()
    if font is None:
        pytest.skip("Нет шрифта с кириллицей")
    doc = pymupdf.open()
    for lines in CONTRACT_PAGES:
        page = doc.new_page()
        y = 72
        for line in lines:
            page.insert_text((60, y), line, fontsize=11, fontname="cyr", fontfile=font)
            y += 18
    path = tmp_path / "contract.pdf"
    doc.save(path)
    return path
