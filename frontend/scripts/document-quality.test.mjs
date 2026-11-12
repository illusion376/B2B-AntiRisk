import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { mapDocument, mapPage } = await loadLib('api');
const { mapDocumentQuality, mapPageQuality, formatProcessingTime, formatQualityPercent, qualityStatusText, qualityTiming, pageQualityWarning, pageRecognitionQuality, documentReviewPages } = await loadLib('document-quality');

const qualityDto = {
  status: 'low', confidence_threshold: 80, confidence: 93.2,
  total_pages: 10, ocr_pages: 5, native_pages: 5, ocr_percent: 50, native_percent: 50,
  measured_ocr_pages: 5,
  review_pages: [{ page: 7, status: 'low', confidence: 69, reason: 'low_confidence', warning: 'Низкая уверенность OCR. Перечитайте оригинал' }],
  manual_review_required: true, warning: 'Результат требует ручной проверки',
  processing_ms: 121000, processing_kind: 'full', sla_ms: 120000, sla_status: 'exceeded',
};
const documentDto = {
  id: 'doc', analysis_id: 'analysis', file_name: 'contract.pdf', relative_path: null,
  analysis_mode: 'llm', file_type: 'pdf', file_size: 1000, status: 'COMPLETED', phase: 'ready',
  label: 'Обработано', progress: 100, total_pages: 10, is_scanned: true, ocr_pages: 5,
  ocr_confidence: 93.2, law_type: null, risk_score: 0, traffic_light: 'ok',
  counts: { critical: 0, warning: 0, low: 0, ok: 1, unknown: 0, unseen: 0 }, rules_checked: 1,
  error_message: null, processing_ms: 121000, has_preview: true, created_at: '2026-11-11T09:00:00Z', updated_at: null,
};
const pageDto = { page: 7, total_pages: 10, width: 595, height: 842, is_ocr: true, ocr_confidence: 69, sections: [] };

test('existing document and page responses carry per-page quality without additional requests', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  assert.equal(document.quality.confidence, 93.2);
  assert.equal(document.quality.manualReviewRequired, true, 'a high document average must not hide a bad page');
  assert.match(qualityStatusText(document.quality), /Есть страницы ниже порога/);
  assert.equal(document.quality.ocrPercent + document.quality.nativePercent, 100);
  assert.equal(document.quality.reviewPages[0].page, 7);
  const page = mapPage({ ...pageDto, quality: {
    status: 'low', confidence: 69, confidence_threshold: 80, manual_review_required: true,
    warning: qualityDto.review_pages[0].warning, reason: 'low_confidence',
  } });
  assert.equal(page.quality.confidenceThreshold, 80);
  assert.equal(page.quality.manualReviewRequired, true);
});

test('legacy responses and native text do not become a fictional 100 percent success', () => {
  assert.equal(mapDocument(documentDto).quality, null);
  assert.equal(mapPage(pageDto).quality, null);
  assert.equal(mapDocumentQuality(null), null);
  assert.equal(mapPageQuality(undefined), null);
  assert.match(qualityStatusText(null), /не подтверждено/);
  assert.equal(formatQualityPercent(null), 'Нет данных');
  const native = mapDocumentQuality({ ...qualityDto, status: 'native', confidence: null,
    ocr_pages: 0, native_pages: 10, ocr_percent: 0, native_percent: 100,
    review_pages: [], manual_review_required: false, warning: null });
  assert.equal(native.confidence, null);
  assert.equal(qualityStatusText(native), 'Текст прочитан напрямую');
});

test('all bad-page markers are available before loading page text and stale page data is ignored', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  assert.equal(pageQualityWarning(document, null, 7), qualityDto.review_pages[0].warning);
  const stalePage = mapPage({ ...pageDto, quality: { status: 'low', confidence: 69,
    confidence_threshold: 80, manual_review_required: true, warning: 'Страница 7', reason: 'low_confidence' } });
  assert.equal(pageQualityWarning(document, stalePage, 8), null);
  assert.equal(pageQualityWarning({ ...document, phase: 'processing' }, stalePage, 7), null);
  assert.equal(pageQualityWarning({ ...document, quality: null }, stalePage, 7), 'Страница 7');
});

test('missing confidence differs from zero confidence and invalid page numbers cannot be navigated to', () => {
  const item = qualityDto.review_pages[0];
  const quality = mapDocumentQuality({ ...qualityDto, confidence: 0, review_pages: [
    { ...item, page: 7, confidence: null }, { ...item, page: 3, confidence: 0 },
    { ...item, page: 0 }, { ...item, page: 11 }, { ...item, page: 3.5 }, { ...item, page: 3, confidence: 0 },
  ] });
  assert.deepEqual(quality.reviewPages.map(item => item.page), [3, 7]);
  assert.equal(quality.reviewPages[0].confidence, 0);
  assert.equal(quality.reviewPages[1].confidence, null);
  assert.equal(formatQualityPercent(quality.confidence), '0%');
  assert.equal(formatQualityPercent(92.2857), '92,3%');
  assert.equal(formatQualityPercent(79.96), '80%', 'displayed percentages are rounded to tenths');
  for (const value of [NaN, Infinity, -1, 101]) assert.equal(formatQualityPercent(value), 'Нет данных');
});

test('timing preserves the server decision at the SLA boundary and highlights an exceedance', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  assert.equal(qualityTiming(document).exceeded, true);
  assert.match(qualityTiming(document).detail, /2 мин.*превышен/);
  const atBoundary = { ...document, quality: { ...document.quality, processingMs: 120000, slaStatus: 'within' } };
  assert.equal(qualityTiming(atBoundary).exceeded, false);
  assert.equal(qualityTiming(atBoundary).detail, 'В пределах норматива 2 мин');
  assert.equal(formatProcessingTime(0), '0 с');
  assert.equal(formatProcessingTime(750), '750 мс');
  assert.equal(formatProcessingTime(123400), '2 мин 3,4 с');
  for (const value of [null, NaN, Infinity, -1]) assert.equal(formatProcessingTime(value), 'Не измерено');
});

test('running, failed, rerun and unmeasured checks cannot show a stale SLA success', () => {
  const document = mapDocument({ ...documentDto, quality: { ...qualityDto, sla_status: 'within' } });
  const active = qualityTiming({ ...document, phase: 'processing' });
  assert.equal(active.label, 'Проверка выполняется');
  assert.doesNotMatch(active.detail, /В пределах/);
  assert.match(qualityTiming({ ...document, phase: 'failed' }).detail, /не подтверждено/);
  assert.match(qualityTiming({ ...document, errorMessage: 'Часть правил не проверена' }).detail, /не подтверждено/);
  const rerun = qualityTiming({ ...document, quality: { ...document.quality, processingKind: 'reanalysis' } });
  assert.match(rerun.detail, /Повторная проверка сохранённого текста/);
  assert.equal(rerun.exceeded, false);
  const unmeasured = qualityTiming({ ...document, quality: { ...document.quality, processingMs: null, slaStatus: 'not_measured' } });
  assert.equal(unmeasured.label, 'Не измерено', 'an explicit absent measurement must not reuse old document time');
  assert.match(unmeasured.detail, /время не измерено/);
  assert.equal(qualityTiming({ ...document, quality: null }).detail, 'Норматив не задан');
});

test('a legacy duration without a recorded measurement scope is visible but not assessed against an SLA', () => {
  const document = mapDocument({ ...documentDto, quality: { ...qualityDto, processing_kind: null, sla_status: 'not_measured' } });
  const timing = qualityTiming(document);
  assert.equal(timing.label, '2 мин 1 с');
  assert.equal(timing.detail, 'Состав измерения не сохранён · сравнение с нормативом недоступно');
  assert.equal(timing.exceeded, false);
  assert.doesNotMatch(timing.detail, /Время проверки не измерено|В пределах/);
});

test('a stored page issue is visible before loading and takes priority over a conflicting page response', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  const unloaded = pageRecognitionQuality(document, null, 7);
  assert.equal(unloaded.status, 'low');
  assert.equal(unloaded.confidence, 69);
  assert.equal(unloaded.confidenceThreshold, 80);
  assert.equal(unloaded.manualReviewRequired, true);
  const conflictingPage = mapPage({ ...pageDto, quality: { status: 'ok', confidence: 99,
    confidence_threshold: 70, manual_review_required: false, warning: null, reason: null } });
  assert.deepEqual(pageRecognitionQuality(document, conflictingPage, 7), unloaded);
  assert.deepEqual(documentReviewPages(document, conflictingPage, 7), document.quality.reviewPages);
});

test('unloaded pages never receive a document average or the previous page measurement', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  const stalePage = mapPage({ ...pageDto, quality: { status: 'ok', confidence: 98,
    confidence_threshold: 80, manual_review_required: false, warning: null, reason: null } });
  assert.equal(pageRecognitionQuality(document, null, 5), null);
  assert.equal(pageRecognitionQuality(document, stalePage, 5), null);
  assert.equal(pageQualityWarning(document, stalePage, 5), null);
  assert.deepEqual(documentReviewPages(document, stalePage, 5).map(item => item.page), [7]);
  for (const page of [0, -1, 10.5, 11, NaN]) assert.equal(pageRecognitionQuality(document, stalePage, page), null);
});

test('page indicators preserve the page policy and do not flag a good page because another one is low', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  const page = mapPage({ ...pageDto, page: 5, quality: { status: 'ok', confidence: 90,
    confidence_threshold: 90, manual_review_required: false, warning: null, reason: null } });
  assert.deepEqual(pageRecognitionQuality(document, page, 5), page.quality);
  assert.equal(pageQualityWarning(document, page, 5), null, 'equality to the saved page threshold is allowed');
  assert.deepEqual(documentReviewPages(document, page, 5).map(item => item.page), [7]);
  const native = mapPage({ ...pageDto, page: 5, is_ocr: false, ocr_confidence: null,
    quality: { status: 'native', confidence: null, confidence_threshold: 80,
      manual_review_required: false, warning: null, reason: null } });
  assert.equal(pageRecognitionQuality(document, native, 5).confidence, null);
  assert.equal(pageQualityWarning(document, native, 5), null);
  assert.deepEqual(pageRecognitionQuality({ ...document, quality: null }, native, 5), native.quality,
    'a valid page response remains authoritative without a document snapshot');
});

test('legacy pages without saved quality are unknown, retaining only a real per-page OCR measurement', () => {
  const document = mapDocument(documentDto);
  const page = mapPage({ ...pageDto, ocr_confidence: 91.66 });
  const quality = pageRecognitionQuality(document, page, 7);
  assert.equal(quality.status, 'unknown');
  assert.equal(quality.manualReviewRequired, true);
  assert.equal(quality.confidence, 91.66);
  assert.equal(quality.confidenceThreshold, null);
  assert.match(pageQualityWarning(document, page, 7), /не подтверждено/);
  assert.deepEqual(documentReviewPages(document, page, 7).map(item => item.page), [7], 'do not invent issues for unopened pages');
  const native = mapPage({ ...pageDto, is_ocr: false, ocr_confidence: null });
  assert.equal(pageRecognitionQuality(document, native, 7).status, 'unknown');
  assert.equal(pageRecognitionQuality(document, native, 7).confidence, null);
  const unknownDocument = { ...document, quality: mapDocumentQuality({ ...qualityDto, status: 'unknown', review_pages: [], confidence_threshold: null }) };
  assert.equal(pageRecognitionQuality(unknownDocument, null, 5), null);
  assert.deepEqual(documentReviewPages(unknownDocument, page, 7).map(item => item.page), [7]);
});

test('problem-page navigation removes invalid and duplicate pages while keeping zero confidence and warning text', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  const issue = document.quality.reviewPages[0];
  document.quality.reviewPages = [issue, { ...issue, page: 0 }, { ...issue, page: 11 },
    { ...issue, page: 3.5 }, { ...issue, page: 3, confidence: 20 },
    { ...issue, page: 3, confidence: 0, warning: '' }];
  const page = mapPage({ ...pageDto, page: 5, quality: { status: 'unknown', confidence: null,
    confidence_threshold: 80, manual_review_required: true, warning: null, reason: 'ocr_failed' } });
  const issues = documentReviewPages(document, page, 5);
  assert.deepEqual(issues.map(item => item.page), [3, 5, 7]);
  assert.equal(issues[0].confidence, 0);
  assert.match(issues[0].warning, /0%.*80%/);
  assert.match(issues[0].warning, /требует ручной проверки/);
  assert.equal(issues[1].reason, 'ocr_failed');
  assert.match(issues[1].warning, /не подтверждено/);
  assert.equal(issues[2].warning, issue.warning);
});

test('low and unknown page states still warn when a response omits the manual-review flag', () => {
  const document = mapDocument({ ...documentDto, quality: { ...qualityDto, review_pages: [] } });
  const page = mapPage({ ...pageDto, quality: { status: 'low', confidence: 79.96,
    confidence_threshold: 80, manual_review_required: false, warning: null, reason: 'low_confidence' } });
  assert.equal(pageRecognitionQuality(document, page, 7).confidence, 79.96);
  assert.match(pageQualityWarning(document, page, 7), /80%.*80%/);
  assert.equal(documentReviewPages(document, page, 7)[0].status, 'low');
  const unknown = { ...page, quality: { ...page.quality, status: 'unknown', confidence: null } };
  assert.match(pageQualityWarning(document, unknown, 7), /не подтверждено/);
  assert.equal(documentReviewPages(document, unknown, 7)[0].status, 'unknown');
});

test('a new processing run hides all previous page warnings and navigation markers', () => {
  const document = mapDocument({ ...documentDto, quality: qualityDto });
  const page = mapPage(pageDto);
  for (const phase of ['uploaded', 'queued', 'processing']) {
    const pending = { ...document, phase };
    assert.equal(pageRecognitionQuality(pending, page, 7), null);
    assert.equal(pageQualityWarning(pending, page, 7), null);
    assert.deepEqual(documentReviewPages(pending, page, 7), []);
  }
});
