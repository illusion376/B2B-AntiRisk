import { CircleHelp } from 'lucide-react';
import { findingSourceLabels } from '@/lib/labels';
import type { Finding } from '@/lib/types';
import './result-badges.css';

export function UnknownResultsBadge({ count }: { count: number }) {
  if (!Number.isFinite(count) || count <= 0) return null;
  return <span className="unknown-results-badge" title="По этим результатам нельзя сделать вывод о наличии или отсутствии риска">
    <CircleHelp size={13} aria-hidden="true" />Недостаточно данных: {count}
  </span>;
}

export function FindingEvidenceBadges({ finding }: { finding: Finding }) {
  const hasUnverifiedQuote = Boolean(finding.quote) && !finding.quoteVerified;
  const lacksEvidence = finding.severity === 'unknown' && !finding.quote;
  return <span className="finding-evidence-badges">
    <small className={`finding-source-badge ${finding.source === 'ERROR' ? 'source-error' : ''}`}>
      {findingSourceLabels[finding.source] ?? (finding.source || 'Источник не указан')}
    </small>
    {(hasUnverifiedQuote || lacksEvidence) && <small className="finding-evidence-missing">
      {hasUnverifiedQuote ? 'Цитата не подтверждена' : 'Нет достаточных оснований для вывода'}
    </small>}
  </span>;
}
