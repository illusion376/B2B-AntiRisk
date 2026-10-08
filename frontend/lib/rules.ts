import type { CheckRule, RiskLevel } from './types';

export const riskLabels: Record<RiskLevel, string> = {
  critical: 'Высокий риск', warning: 'Средний риск', low: 'Низкий риск',
};

const riskOrder: Record<RiskLevel, number> = { critical: 0, warning: 1, low: 2 };

export function compareRulesByRisk(left: CheckRule, right: CheckRule): number {
  return riskOrder[left.severity] - riskOrder[right.severity];
}
