'use client';

import { useId } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, Clock3, FileText, LoaderCircle } from 'lucide-react';
import type { DocumentInfo, DocumentQuality } from '@/lib/types';
import { formatProcessingTime, formatQualityPercent, isQualityPending, qualityTiming } from '@/lib/document-quality';
import './document-quality.css';

function requiresManualReview(quality: DocumentQuality | null | undefined): boolean {
  return !quality || quality.manualReviewRequired || quality.status === 'low' || quality.status === 'unknown';
}

const pagePlural = new Intl.PluralRules('ru-RU');

function pageCount(count: number): string {
  const form = pagePlural.select(count);
  return `${count} ${form === 'one' ? 'страница' : form === 'few' ? 'страницы' : 'страниц'}`;
}

export function DocumentReviewMetrics({ document }: { document: DocumentInfo }) {
  const sectionId = useId();
  const pending = isQualityPending(document);
  const quality = pending ? null : document.quality;
  const needsReview = !pending && requiresManualReview(quality);
  const native = quality?.status === 'native';
  const hasSources = quality && quality.totalPages > 0 && quality.ocrPercent !== null && quality.nativePercent !== null;
  const totalPages = pending ? 0 : quality?.totalPages || document.totalPages;
  const status = pending ? 'Проверка выполняется'
    : needsReview ? 'Требуется ручная проверка'
      : native ? 'Текстовый слой' : 'Распознавание без предупреждений';
  const assessment = pending ? 'Оценка появится после распознавания'
    : needsReview ? quality?.warning || 'Проверьте вручную страницы с низким или неизвестным качеством распознавания'
      : native ? 'Документ содержит текстовый слой'
        : 'Страниц с низким или неизвестным качеством распознавания не выявлено';

  return <div className="document-review-metrics">
    <details key={document.id} className={`quality-disclosure${needsReview ? ' needs-review' : ''}`}>
      <summary className="quality-disclosure-summary">
        <span className="quality-disclosure-icon" aria-hidden="true">{pending
          ? <LoaderCircle size={16} className="spin" />
          : needsReview ? <AlertTriangle size={16} />
            : native ? <FileText size={16} /> : <CheckCircle2 size={16} />}</span>
        <span className="quality-disclosure-heading"><strong>{status}</strong><span>Качество распознавания</span></span>
        <strong className={`quality-disclosure-value${native || !quality || quality.confidence === null ? ' is-label' : ''}`}>{pending ? 'Определяется…' : native ? 'Без OCR' : formatQualityPercent(quality?.confidence)}</strong>
        <span className="quality-disclosure-toggle"><span className="quality-label-closed">Подробнее</span><span className="quality-label-open">Свернуть</span><ChevronDown size={14} aria-hidden="true" /></span>
      </summary>
      <div className="quality-disclosure-content">
        <section className="quality-assessment" aria-labelledby={`${sectionId}-assessment`}>
          <h3 id={`${sectionId}-assessment`}>Оценка распознавания</h3>
          <p className={needsReview ? 'quality-assessment-warning' : 'quality-assessment-note'} role={needsReview ? 'status' : undefined}>{assessment}</p>
        </section>
        <section className="quality-composition" aria-labelledby={`${sectionId}-composition`}>
          <div className="quality-composition-heading"><h3 id={`${sectionId}-composition`}>Состав документа</h3>{totalPages > 0 && <span>{pageCount(totalPages)}</span>}</div>
          {hasSources ? <>
            <div className="quality-composition-bar" aria-hidden="true"><span style={{ width: `${quality.ocrPercent}%` }} /></div>
            <div className="quality-composition-legend"><span>OCR {formatQualityPercent(quality.ocrPercent)} · {pageCount(quality.ocrPages)}</span><span>Текстовый слой {formatQualityPercent(quality.nativePercent)} · {pageCount(quality.nativePages)}</span></div>
          </> : <p className="quality-assessment-note">{pending ? 'Состав документа появится после распознавания' : 'Источник страниц не зафиксирован'}</p>}
        </section>
      </div>
    </details>
  </div>;
}

export function DocumentQualityBadges({ document }: { document: DocumentInfo }) {
  if (isQualityPending(document) || document.phase === 'unsupported') return null;
  const quality = document.quality;
  const timing = qualityTiming(document);
  const needsReview = requiresManualReview(quality);
  const hasDuration = quality?.processingMs !== null && quality?.processingMs !== undefined;
  if (!needsReview && !hasDuration) return null;
  return <div className="document-quality-badges" aria-label="Качество проверки документа">
    {needsReview && <span className="quality-list-warning" title={quality?.warning || 'Нет достоверных сведений о качестве распознавания'}><AlertTriangle size={12} aria-hidden="true" />Нужна ручная проверка</span>}
    {hasDuration && <span className={timing.exceeded ? 'quality-list-warning' : ''} title={timing.detail}><Clock3 size={12} aria-hidden="true" />{formatProcessingTime(quality.processingMs)}{timing.exceeded ? ' · норматив превышен' : quality.processingKind === 'reanalysis' ? ' · повторная проверка' : ''}</span>}
  </div>;
}
