'use client';

import { AlertTriangle, ChevronDown, ChevronRight, FileText, ScanText } from 'lucide-react';
import { formatQualityPercent } from '@/lib/document-quality';
import type { PageQuality, ReviewPageQuality } from '@/lib/types';
import { IconButton } from './ui';
import './page-quality-controls.css';

interface Props {
  page: number;
  quality: PageQuality | null;
  reviewPages: ReviewPageQuality[];
  pending: boolean;
  loading: boolean;
  onPage: (page: number) => void;
}

export function PageQualityControls({ page, quality, reviewPages, pending, loading, onPage }: Props) {
  const needsReview = Boolean(quality && (quality.manualReviewRequired || quality.status === 'low' || quality.status === 'unknown'));
  const native = quality?.status === 'native';
  const nextPage = reviewPages.find(item => item.page > page)?.page ?? reviewPages[0]?.page;
  const label = pending ? 'Оценка определяется'
    : !quality ? loading ? 'Оценка загружается' : 'Нет данных о качестве'
      : native ? 'Текстовый слой'
        : quality.confidence !== null ? `Уверенность ${formatQualityPercent(quality.confidence)}` : 'Качество не подтверждено';
  const threshold = !native && quality?.confidenceThreshold !== null && quality?.confidenceThreshold !== undefined
    ? `Требуемый уровень: ${formatQualityPercent(quality.confidenceThreshold)}` : null;
  const warning = quality?.warning || (quality?.status === 'low'
    ? 'Низкое качество распознавания. Результат требует ручной проверки'
    : 'Качество распознавания не подтверждено. Результат требует ручной проверки');

  function goToPage(value: string) {
    const target = Number(value);
    if (reviewPages.some(item => item.page === target)) onPage(target);
  }

  return <section className={`page-quality-controls${needsReview ? ' needs-review' : ''}`} aria-label="Качество распознавания страниц">
    <div className="page-quality-current" role="status">
      {needsReview ? <AlertTriangle size={15} aria-hidden="true" /> : native ? <FileText size={15} aria-hidden="true" /> : <ScanText size={15} aria-hidden="true" />}
      <span>Страница {page}</span>
      <strong>{label}</strong>
      {threshold && <small>{threshold}</small>}
    </div>
    {reviewPages.length > 0 && <div className="page-quality-navigation" role="group" aria-label="Переход к страницам для ручной проверки">
      <label className="page-quality-select">
        <span className="sr-only">Страницы для ручной проверки: {reviewPages.length}</span>
        <select value="" onChange={event => goToPage(event.target.value)}>
          <option value="">Требуют проверки: {reviewPages.length}</option>
          {reviewPages.map(item => <option key={item.page} value={item.page}>Страница {item.page} · {item.status === 'low' && item.confidence !== null ? `${formatQualityPercent(item.confidence)} — ниже порога` : 'качество не подтверждено'}</option>)}
        </select>
        <ChevronDown size={13} aria-hidden="true" />
      </label>
      <IconButton label={`Следующая страница для ручной проверки: ${nextPage}`} disabled={nextPage === page} onClick={() => { if (nextPage !== undefined) onPage(nextPage); }}><ChevronRight size={16} /></IconButton>
    </div>}
    {needsReview && <div className="page-quality-detail" role="status">
      <strong>{quality?.status === 'low' ? 'Низкое качество распознавания страницы' : 'Качество страницы не подтверждено'}</strong>
      <span>{warning}</span>
    </div>}
  </section>;
}
