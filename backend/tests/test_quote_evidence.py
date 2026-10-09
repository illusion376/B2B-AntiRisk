"""Evidence is exact in both the selected fragment and its actual document pages."""
import pytest

from app.services.quotes import locate_quote


def _page(number, *lines):
    words = []
    for line_index, text in enumerate(lines):
        x = 0
        for word in text.split():
            words.append([x, line_index * 20, x + len(word) * 8, line_index * 20 + 15, word, line_index])
            x += len(word) * 8 + 5
    return {"page_number": number, "words": words}


def _strict(pages, quote, candidate, hint=(1, 1)):
    return locate_quote(pages, quote, hint, candidate_text=candidate, strict=True)


def test_strict_accepts_whitespace_and_returns_original_document_text():
    quote = "Поставщик уплачивает штраф в размере 0,1% от стоимости Контракта"
    pages = [_page(1, "6.2. Поставщик уплачивает штраф в размере 0,1%", "от стоимости Контракта.")]
    candidate = "6.2. Поставщик\tуплачивает штраф\u00a0в размере 0,1%\nот стоимости Контракта."
    match = _strict(pages, quote, candidate)
    assert match.verified and match.score == 100
    assert match.page_number == 1 and match.clause == "6.2"
    assert match.text == "Поставщик уплачивает штраф в размере 0,1%\nот стоимости Контракта."
    assert len(match.highlights[0]["rects"]) == 2


@pytest.mark.parametrize("candidate", [
    "Размер штрафа не ограничен общей суммой Контракта.",
    "Размер штрафа не огра-\nничен общей суммой Контракта.",
    "Размер штрафа не огра\u00adничен общей суммой Контракта.",
])
def test_strict_accepts_alphabetic_line_wrap_and_soft_hyphen(candidate):
    pages = [_page(1, "6.2. Размер штрафа не огра-", "ничен общей суммой Контракта.")]
    match = _strict(pages, "Размер штрафа не ограничен общей суммой Контракта.", candidate)
    assert match.verified and match.clause == "6.2"
    assert match.text == "Размер штрафа не огра-\nничен общей суммой Контракта."
    assert len(match.highlights[0]["rects"]) == 2


@pytest.mark.parametrize(("actual", "quote"), [
    ("Ответственность не ограничена суммой контракта.", "Ответственность ограничена суммой контракта."),
    ("Ответственность неограничена суммой контракта.", "ограничена суммой контракта."),
    ("Ответственность не ограничена суммой контракта.", "ограничена суммой контракта."),
    ("Условия без ограничения суммы ответственности.", "ограничения суммы ответственности."),
    ("Штраф составляет 11 процентов цены контракта.", "Штраф составляет 1 процентов цены контракта."),
    ("Штраф составляет 0.01% цены контракта.", "Штраф составляет 0.1% цены контракта."),
    ("Штраф составляет 0,01% цены контракта.", "Штраф составляет 0,1% цены контракта."),
    ("Штраф составляет -1% цены контракта.", "Штраф составляет 1% цены контракта."),
    ("Изменение составляет −1% цены контракта.", "Изменение составляет 1% цены контракта."),
    ("Изменение составляет +1% цены контракта.", "Изменение составляет 1% цены контракта."),
    ("Размер штрафа составляет 0,1% цены контракта.", "Размер штрафа составляет 0.1% цены контракта."),
    ("Штраф: 1% цены контракта, за день.", "Штраф 1% цены контракта за день."),
    ("Сумма социально-экономического ущерба не ограничена.", "Сумма социальноэкономического ущерба не ограничена."),
    ("Штраф составляет - 1% цены контракта.", "1% цены контракта."),
    ("Штраф составляет 11% цены контракта.", "1% цены контракта."),
    ("Штраф составляет 0.1% цены контракта.", "1% цены контракта."),
])
def test_strict_rejects_changed_negation_numbers_signs_and_punctuation(actual, quote):
    assert not _strict([_page(1, actual)], quote, actual).verified
    # An incorrect candidate cannot make an altered quote match the real page.
    assert not _strict([_page(1, actual)], quote, quote).verified


def test_strict_does_not_remove_a_numeric_minus_at_line_end():
    pages = [_page(1, "Штраф составляет 1-", "11 процентов цены контракта.")]
    assert not _strict(pages, "Штраф составляет 111 процентов цены контракта.",
                       "Штраф составляет 111 процентов цены контракта.").verified


def test_strict_wrong_candidate_is_rejected_even_when_quote_exists_on_same_page():
    quote = "Ответственность поставщика не ограничена суммой контракта."
    candidate = "Оплата производится в течение десяти дней."
    assert not _strict([_page(1, candidate, quote)], quote, candidate).verified


@pytest.mark.parametrize("actual_page", [1, 3, 8])
def test_strict_does_not_search_adjacent_or_global_pages(actual_page):
    quote = "Ответственность поставщика не ограничена суммой контракта."
    pages = [_page(2, "Оплата производится в течение десяти дней."), _page(actual_page, quote)]
    assert not _strict(pages, quote, quote, hint=(2, 2)).verified


def test_strict_supports_the_full_referenced_page_range():
    quote = "Ответственность поставщика не ограничена суммой контракта."
    pages = [_page(1, "6.2. Ответственность поставщика"), _page(2, "не ограничена суммой контракта.")]
    match = _strict(pages, quote, quote, hint=(1, 2))
    assert match.verified and {h["page"] for h in match.highlights} == {1, 2}


@pytest.mark.parametrize(("hint", "candidate"), [(None, "Размер штрафа не ограничен."), ((1, 1), None), ((2, 1), "Размер штрафа не ограничен.")])
def test_strict_requires_a_candidate_and_valid_page_scope(hint, candidate):
    quote = "Размер штрафа не ограничен."
    assert not _strict([_page(1, quote)], quote, candidate, hint).verified


def test_strict_rejects_punctuation_only_quote():
    assert not _strict([_page(1, "...")], "...", "...").verified


def test_default_fuzzy_match_never_verifies_an_altered_number():
    actual = "Штраф составляет 11 процентов цены контракта за день просрочки."
    quote = "Штраф составляет 1 процентов цены контракта за день просрочки."
    match = locate_quote([_page(1, actual)], quote, (1, 1))
    assert not match.verified
    assert match.text == actual and match.highlights


def test_default_fuzzy_substring_with_perfect_score_is_not_verified():
    # Partial ratio may be 100 for a substring inside a larger word.
    match = locate_quote([_page(1, "неограничена общая ответственность поставщика")],
                         "ограничена общая ответственность поставщика", (1, 1))
    assert not match.verified and match.score == 100


def test_default_exact_matching_preserves_legacy_case_and_quote_normalization():
    match = locate_quote([_page(1, "6.2. Размер штрафа не огра-", "ничен общей суммой Контракта.")],
                         "НЕ ОГРАНИЧЕН общей суммой «Контракта»", (1, 1))
    assert match.verified and match.clause == "6.2"


def test_strict_preserves_a_literal_compound_hyphen_at_line_end():
    quote = "Сумма социально-экономического ущерба не ограничена."
    match = _strict([_page(1, "Сумма социально-", "экономического ущерба не ограничена.")], quote, quote)
    assert match.verified
    assert match.text == "Сумма социально-\nэкономического ущерба не ограничена."
