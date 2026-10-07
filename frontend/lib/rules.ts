import type { RiskLevel } from './types';

export const riskLabels: Record<RiskLevel, string> = {
  critical: 'Высокий риск', warning: 'Средний риск', low: 'Низкий риск',
};
