'use client';

import { AlertTriangle, Clock3, FileScan, ScanText } from 'lucide-react';
import type { DocumentInfo, DocumentQuality } from '@/lib/types';
import { formatProcessingTime, formatQualityPercent, isQualityPending, qualityTiming } from '@/lib/document-quality';
import './document-quality.css';

function requiresManualReview(quality: DocumentQuality | null | undefined): boolean {
  return !quality || quality.manualReviewRequired || quality.status === 'low' || quality.status === 'unknown';
}

export function DocumentReviewMetrics({ document }: { document: DocumentInfo }) {
  const pending = isQualityPending(document);
  const quality = pending ? null : document.quality;
  const needsReview = !pending && requiresManualReview(quality);
  const native = quality?.status === 'native';
  const hasSources = quality && quality.totalPages > 0 && quality.ocrPercent !== null && quality.nativePercent !== null;
  return <dl className="document-review-metrics" aria-label="Качество распознавания и OCR">
    <div className={`quality-metric${needsReview ? ' quality-needs-review' : ''}`}>
      <dt><ScanText size={14} aria-hidden="true" />Качество распознавания</dt>
      <dd className="quality-confidence-value">{pending ? 'Определяется…' : native ? 'Без OCR' : formatQualityPercent(quality?.confidence)}</dd>
      <dd className="quality-caption">{pending
        ? 'Оценка появится после распознавания'
        : native ? 'Текстовый слой'
          : quality?.confidenceThreshold !== null && quality?.confidenceThreshold !== undefined
            ? `Требуемый уровень: ${formatQualityPercent(quality.confidenceThreshold)}`
            : 'Требуемый уровень не зафиксирован'}</dd>
      {quality && quality.ocrPages > 0 && <dd className="quality-caption">Оценено OCR-страниц: {quality.measuredOcrPages} из {quality.ocrPages}</dd>}
      {needsReview && <dd className="quality-review-warning" role="status"><AlertTriangle size={14} aria-hidden="true" /><span>{quality?.warning || 'Качество распознавания не подтверждено. Результат требует ручной проверки'}</span></dd>}
    </div>
    <div className="quality-metric">
      <dt><FileScan size={14} aria-hidden="true" />OCR</dt>
      {hasSources ? <>
        <dd>{formatQualityPercent(quality.ocrPercent)} <small className="quality-page-count">{quality.ocrPages} из {quality.totalPages} стр.</small></dd>
        <dd className="quality-caption">Доля страниц-изображений</dd>
        <dd className="quality-caption">Текстовый слой: {formatQualityPercent(quality.nativePercent)} · {quality.nativePages} стр.</dd>
        <dd className="quality-source-bar" aria-hidden="true"><span style={{ width: `${quality.ocrPercent}%` }} /></dd>
      </> : <><dd>{pending ? 'Определяется…' : 'Нет данных'}</dd><dd className="quality-caption">{pending ? 'Доля OCR появится после распознавания' : 'Источник страниц не зафиксирован'}</dd></>}
    </div>
  </dl>;
}

export function DocumentQualityBadges({ document }: { document: DocumentInfo }) {
  if (isQualityPending(document) || document.phase === 'unsupported') return null;
  const quality = document.quality;
  const timing = qualityTiming(document);
  const needsReview = requiresManualReview(quality);
  const hasDuration = quality?.processingMs !== null && quality?.processingMs !== undefined;
  if (!needsReview && !hasDuration) return null;
  return <div className="document-quality-badges" aria-label="Качество проверки документа">
    {needsReview && <span className="quality-list-warning" title={quality?.warning || 'Нет достоверных сведений о качестве распознавания'}><AlertTriangle size={12} aria-hidden="true" />Нужна ручная проверка{quality?.reviewPages.length ? ` · стр.: ${quality.reviewPages.slice(0, 3).map(item => item.page).join(', ')}${quality.reviewPages.length > 3 ? ` и ещё ${quality.reviewPages.length - 3}` : ''}` : ''}</span>}
    {hasDuration && <span className={timing.exceeded ? 'quality-list-warning' : ''} title={timing.detail}><Clock3 size={12} aria-hidden="true" />{formatProcessingTime(quality.processingMs)}{timing.exceeded ? ' · норматив превышен' : quality.processingKind === 'reanalysis' ? ' · повторная проверка' : ''}</span>}
  </div>;
}
