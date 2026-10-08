import type { AnalysisMode, RiskLevel, Severity } from './types';

// Labels describe results, not the existence of a verified legal violation.
export const statusLabels = { unseen: 'Не просмотрено', accepted: 'Принято', dismissed: 'Отклонено' } as const;
export const severityLabels: Record<Severity, string> = {
  critical: 'Критические замечания', warning: 'Требуют внимания', low: 'Низкий риск',
  unknown: 'Недостаточно данных', ok: 'Без замечаний',
};
export const analysisModeLabels: Record<AnalysisMode, string> = {
  llm: 'LLM-анализ', nli: 'NLI-анализ', keyword: 'Поиск по словам',
};
export const findingSourceLabels: Record<string, string> = {
  LLM: 'LLM-анализ', NLI: 'NLI-анализ', HEURISTIC: 'Поиск по словам', ERROR: 'Ошибка анализа',
};

export function isRiskSeverity(severity: Severity): severity is RiskLevel {
  return severity === 'critical' || severity === 'warning' || severity === 'low';
}
