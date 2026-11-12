import type { DocumentQualityDto, PageQualityDto } from './api-types';
import type { DocumentInfo, DocumentQuality, PageContent, PageQuality, ReviewPageQuality } from './types';

const decimal = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const nonNegative = (value: number | null | undefined): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const percent = (value: number | null | undefined): number | null => {
  const result = nonNegative(value);
  return result !== null && result <= 100 ? result : null;
};

export function mapDocumentQuality(value: DocumentQualityDto | null | undefined): DocumentQuality | null {
  if (!value) return null;
  const pages = new Map<number, ReviewPageQuality>();
  for (const item of value.review_pages) {
    if (Number.isInteger(item.page) && item.page >= 1 && item.page <= value.total_pages) {
      pages.set(item.page, { ...item, confidence: percent(item.confidence) });
    }
  }
  return {
    status: value.status,
    confidenceThreshold: percent(value.confidence_threshold), confidence: percent(value.confidence),
    totalPages: value.total_pages, ocrPages: value.ocr_pages, nativePages: value.native_pages,
    ocrPercent: percent(value.ocr_percent), nativePercent: percent(value.native_percent),
    measuredOcrPages: value.measured_ocr_pages,
    reviewPages: [...pages.values()].sort((a, b) => a.page - b.page),
    manualReviewRequired: value.manual_review_required, warning: value.warning,
    processingMs: nonNegative(value.processing_ms), processingKind: value.processing_kind,
    slaMs: nonNegative(value.sla_ms), slaStatus: value.sla_status,
  };
}

export function mapPageQuality(value: PageQualityDto | null | undefined): PageQuality | null {
  return value ? {
    status: value.status, confidence: percent(value.confidence), confidenceThreshold: percent(value.confidence_threshold),
    manualReviewRequired: value.manual_review_required, warning: value.warning, reason: value.reason,
  } : null;
}

export function formatQualityPercent(value: number | null | undefined): string {
  const valid = percent(value);
  return valid === null ? 'Нет данных' : `${decimal.format(valid)}%`;
}

export function formatProcessingTime(value: number | null | undefined): string {
  const valid = nonNegative(value);
  if (valid === null) return 'Не измерено';
  if (valid > 0 && valid < 1000) return `${Math.round(valid)} мс`;
  const seconds = Math.round(valid / 100) / 10;
  if (seconds < 60) return `${decimal.format(seconds)} с`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round((seconds - minutes * 60) * 10) / 10;
  return `${minutes} мин${remainder ? ` ${decimal.format(remainder)} с` : ''}`;
}

export function isQualityPending(document: Pick<DocumentInfo, 'phase'>): boolean {
  return document.phase === 'uploaded' || document.phase === 'queued' || document.phase === 'processing';
}

export function qualityStatusText(quality: DocumentQuality | null | undefined): string {
  switch (quality?.status) {
    case 'ok': return 'В пределах порога';
    case 'low': return 'Есть страницы ниже порога';
    case 'native': return 'Текст прочитан напрямую';
    default: return 'Качество не подтверждено';
  }
}

/** SLA is assessed by the server; a rerun and an incomplete run are never a passing full check. */
export function qualityTiming(document: Pick<DocumentInfo, 'phase' | 'errorMessage' | 'quality' | 'processingMs'>): { label: string; detail: string; exceeded: boolean } {
  if (isQualityPending(document)) return { label: 'Проверка выполняется', detail: 'Время появится после завершения', exceeded: false };
  const quality = document.quality;
  const label = formatProcessingTime(quality ? quality.processingMs : document.processingMs);
  if (quality?.processingKind === 'reanalysis') return {
    label, detail: 'Повторная проверка сохранённого текста · норматив полного цикла не применяется', exceeded: false,
  };
  if (quality?.slaStatus === 'exceeded') return {
    label, detail: `Норматив ${formatProcessingTime(quality.slaMs)} превышен`, exceeded: true,
  };
  if (document.phase === 'failed' || document.errorMessage) return {
    label, detail: 'Проверка завершилась с ошибкой · соблюдение норматива не подтверждено', exceeded: false,
  };
  if (quality?.slaStatus === 'within') return {
    label, detail: `В пределах норматива ${formatProcessingTime(quality.slaMs)}`, exceeded: false,
  };
  if (quality?.slaStatus === 'not_measured') return {
    label,
    detail: quality.processingKind === null && quality.processingMs !== null
      ? 'Состав измерения не сохранён · сравнение с нормативом недоступно'
      : quality.slaMs !== null ? `Норматив ${formatProcessingTime(quality.slaMs)} · время не измерено` : 'Время проверки не измерено',
    exceeded: false,
  };
  if (quality?.slaStatus === 'not_applicable') return {
    label, detail: 'Проверка не завершена полностью · соблюдение норматива не подтверждено', exceeded: false,
  };
  return { label, detail: 'Норматив не задан', exceeded: false };
}

function isDocumentPage(document: DocumentInfo, page: number): boolean {
  return Number.isInteger(page) && page >= 1 && page <= document.totalPages;
}

function qualityNeedsReview(quality: PageQuality): boolean {
  return quality.manualReviewRequired || quality.status === 'low' || quality.status === 'unknown';
}

function recognitionWarning(quality: PageQuality): string {
  if (quality.warning?.trim()) return quality.warning;
  if (quality.status === 'low') {
    const reason = quality.confidence !== null && quality.confidenceThreshold !== null
      ? `Уверенность OCR ${formatQualityPercent(quality.confidence)} ниже порога ${formatQualityPercent(quality.confidenceThreshold)}`
      : 'Низкое качество распознавания страницы';
    return `${reason}. Результат требует ручной проверки`;
  }
  return 'Качество распознавания страницы не подтверждено. Перечитайте страницу в оригинале';
}

function storedPageQuality(document: DocumentInfo, issue: ReviewPageQuality): PageQuality & { reason: string } {
  return {
    status: issue.status,
    confidence: percent(issue.confidence),
    confidenceThreshold: percent(document.quality?.confidenceThreshold),
    manualReviewRequired: true,
    warning: issue.warning || null,
    reason: issue.reason || (issue.status === 'low' ? 'low_confidence' : 'confidence_missing'),
  };
}

/** Use the stored issue before page loading; never assign the document average to a page. */
export function pageRecognitionQuality(document: DocumentInfo, pageContent: PageContent | null, page: number): PageQuality | null {
  if (isQualityPending(document) || !isDocumentPage(document, page)) return null;
  const stored = document.quality?.reviewPages.find(item => item.page === page);
  if (stored) return storedPageQuality(document, stored);
  if (pageContent?.page !== page) return null;
  if (pageContent.quality) return pageContent.quality;
  // Older page responses have no saved policy, even when they contain an OCR measurement.
  return {
    status: 'unknown', confidence: pageContent.isOcr ? percent(pageContent.ocrConfidence) : null,
    confidenceThreshold: null, manualReviewRequired: true, warning: null, reason: 'quality_not_recorded',
  };
}

export function pageQualityWarning(document: DocumentInfo, pageContent: PageContent | null, page: number): string | null {
  const quality = pageRecognitionQuality(document, pageContent, page);
  return quality && qualityNeedsReview(quality) ? recognitionWarning(quality) : null;
}

/** All known problem pages are available without requesting each page's text. */
export function documentReviewPages(document: DocumentInfo, pageContent: PageContent | null, page: number): ReviewPageQuality[] {
  if (isQualityPending(document)) return [];
  const issues = new Map<number, ReviewPageQuality>();
  for (const item of document.quality?.reviewPages ?? []) {
    if (!isDocumentPage(document, item.page)) continue;
    const quality = storedPageQuality(document, item);
    issues.set(item.page, {
      ...item, confidence: quality.confidence, reason: quality.reason, warning: recognitionWarning(quality),
    });
  }
  const current = pageRecognitionQuality(document, pageContent, page);
  if (current && qualityNeedsReview(current) && !issues.has(page)) {
    issues.set(page, {
      page, status: current.status === 'low' ? 'low' : 'unknown', confidence: percent(current.confidence),
      reason: current.reason || (current.status === 'low' ? 'low_confidence' : 'quality_not_recorded'),
      warning: recognitionWarning(current),
    });
  }
  return [...issues.values()].sort((left, right) => left.page - right.page);
}
