import { findingSourceLabels } from '@/lib/labels';
import type { Finding } from '@/lib/types';
import './result-badges.css';

export function FindingEvidenceBadges({ finding }: { finding: Finding }) {
  const showSource = finding.source !== 'LLM';
  const hasUnverifiedQuote = Boolean(finding.quote) && !finding.quoteVerified;
  const lacksEvidence = finding.severity === 'unknown' && !finding.quote;
  if (!showSource && !hasUnverifiedQuote && !lacksEvidence) return null;
  return <span className="finding-evidence-badges">
    {showSource && <small className={`finding-source-badge ${finding.source === 'ERROR' ? 'source-error' : ''}`}>
      {findingSourceLabels[finding.source] ?? (finding.source || 'Источник не указан')}
    </small>}
    {(hasUnverifiedQuote || lacksEvidence) && <small className="finding-evidence-missing">
      {hasUnverifiedQuote ? 'Цитата не подтверждена' : 'Нет достаточных оснований для вывода'}
    </small>}
  </span>;
}
