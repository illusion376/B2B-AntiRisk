"""Одинаковые пояснения метрик качества во всех форматах отчёта."""

from app.schemas import DocumentQuality
from app.services.document_quality import format_quality_percent

QUALITY_TITLE = "Качество проверки документа"
QUALITY_LIMITATION = (
    "Уверенность OCR характеризует распознавание текста, а не точность юридических выводов. "
    "Доля сканов включает страницы, для которых распознавание не удалось или было отключено."
)


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def duration_label(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "Не измерено"
    if milliseconds < 1000:
        return f"{milliseconds} мс"
    minutes, rest = divmod(milliseconds, 60_000)
    if minutes:
        return f"{minutes} мин" + (f" {_number(rest / 1000)} с" if rest else "")
    return f"{_number(milliseconds / 1000)} с"


def quality_warning(quality: DocumentQuality) -> str | None:
    if quality.manual_review_required:
        base = "Результат требует ручной проверки"
        detail = quality.warning or ""
        return detail if base.lower() in detail.lower() else f"{base}. {detail}".strip()
    return quality.warning


def quality_rows(quality: DocumentQuality) -> list[tuple[str, str]]:
    """Возвращает человеческие подписи, не пересчитывая серверные пороги и статусы."""
    confidence = format_quality_percent(quality.confidence) if quality.confidence is not None else "Не измерена"
    if quality.status == "native":
        assessment = "Текстовый слой — уверенность OCR не измерялась"
    elif quality.status == "low":
        assessment = f"Низкое качество на отдельных страницах. Средняя уверенность OCR: {confidence}"
    elif quality.status == "ok":
        assessment = f"Измеренная уверенность OCR соответствует порогу: {confidence}"
    else:
        assessment = f"Качество распознавания известно не полностью. Средняя уверенность OCR: {confidence}"

    if quality.ocr_percent is None or quality.native_percent is None:
        sources = "Нет сохранённых данных о способе чтения страниц"
    else:
        sources = (
            f"Сканы / OCR: {quality.ocr_pages} из {quality.total_pages} "
            f"({format_quality_percent(quality.ocr_percent)}). "
            f"Текстовый слой: {quality.native_pages} из {quality.total_pages} "
            f"({format_quality_percent(quality.native_percent)})"
        )

    if quality.processing_kind == "full":
        scope = "Полный цикл: подготовка документа, распознавание, индексация и проверка; без ожидания в очереди"
    elif quality.processing_kind == "reanalysis":
        scope = "Повторная проверка ранее извлечённого текста; без OCR, индексации и ожидания в очереди"
    else:
        scope = "Состав измерения не сохранён"

    if quality.sla_status == "exceeded" and quality.sla_ms is not None:
        excess = max(0, (quality.processing_ms or 0) - quality.sla_ms)
        sla = f"Превышен: лимит {duration_label(quality.sla_ms)}, превышение {duration_label(excess)}"
    elif quality.sla_status == "within" and quality.sla_ms is not None:
        sla = f"В пределах норматива: лимит {duration_label(quality.sla_ms)}"
    elif quality.sla_status == "not_applicable":
        sla = ("Норматив полного цикла неприменим к повторной проверке"
               if quality.processing_kind == "reanalysis" else
               "Соответствие нормативу не оценено: проверка не завершена полностью")
        if quality.sla_ms is not None:
            sla += f"; лимит {duration_label(quality.sla_ms)}"
    elif quality.sla_status == "not_configured":
        sla = "Норматив не задан"
    else:
        sla = "Соответствие нормативу не оценено"
        if quality.sla_ms is not None:
            sla += f"; лимит {duration_label(quality.sla_ms)}"

    rows = [
        ("Оценка распознавания", assessment),
        ("Порог уверенности OCR", format_quality_percent(quality.confidence_threshold)
         if quality.confidence_threshold is not None else "Не сохранён"),
        ("Источник текста", sources),
        ("Измерено качество OCR", f"{quality.measured_ocr_pages} из {quality.ocr_pages} страниц"
         if quality.ocr_percent is not None else "Нет данных"),
        ("Время проверки", duration_label(quality.processing_ms)),
        ("Что входит во время", scope),
        ("Норматив времени", sla),
    ]
    warning = quality_warning(quality)
    if warning:
        rows.append(("Предупреждение", warning))
    if quality.review_pages:
        rows.append(("Страницы для ручной проверки", ", ".join(str(p.page) for p in quality.review_pages)))
    return rows


def quality_page_rows(quality: DocumentQuality) -> list[tuple[str, str]]:
    return [
        (f"Страница {page.page}",
         page.warning.rstrip(". ") + (f". Уверенность OCR: {format_quality_percent(page.confidence)}"
                               if page.confidence is not None else ""))
        for page in quality.review_pages
    ]
