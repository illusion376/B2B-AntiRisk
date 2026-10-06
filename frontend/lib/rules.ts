import type { CheckRule, Finding, Project, ReviewStatus, RiskLevel } from './types';
import { findings } from './mock-data';
import { createDemoProject, parseProjects } from './projects';

export const riskLabels: Record<RiskLevel, string> = {
  critical: 'Высокий риск', warning: 'Средний риск', low: 'Низкий риск',
};
export const defaultRules: CheckRule[] = findings.map(f => ({
  id: f.id, title: f.title, description: f.description, category: f.category,
  severity: f.severity === 'ok' ? 'low' : f.severity, enabled: true,
}));
// Keep the original key so existing users are migrated without losing their rules.
export const STORAGE_KEY = 'b2b-antirisk:workspace:v1';
export interface SavedWorkspace {
  version: 2;
  rules: CheckRule[];
  nextRuleId: number;
  projects: Project[];
  statuses: Record<number, ReviewStatus>;
}

export function applyRules(items: Finding[], rules: CheckRule[]): Finding[] {
  const byId = new Map(rules.filter(rule => rule.enabled).map(rule => [rule.id, rule]));
  return items.flatMap(finding => {
    const rule = byId.get(finding.id);
    if (!rule) return [];
    // A successful check stays successful; a low-risk finding is still a finding.
    return [{ ...finding, title: rule.title, description: rule.description, category: rule.category, severity: finding.severity === 'ok' ? 'ok' as const : rule.severity }];
  });
}

export function parseWorkspace(raw: string): SavedWorkspace | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return null;
    const data = value as Partial<Omit<SavedWorkspace, 'version'>> & {version?:number;documentName?:unknown};
    if (![1,2].includes(data.version ?? 0) || !Array.isArray(data.rules)) return null;
    let projects: Project[] | null;
    if (data.version === 1) {
      if (typeof data.documentName !== 'string' || !data.documentName.trim() || data.documentName.length > 110) return null;
      projects = [createDemoProject(data.documentName)];
    } else projects = parseProjects(data.projects);
    if (!projects) return null;
    const ids = new Set<number>();
    for (const rule of data.rules) {
      if (!rule || typeof rule !== 'object' || !Number.isSafeInteger(rule.id) || rule.id < 1 || ids.has(rule.id) || typeof rule.title !== 'string' || !rule.title.trim() || rule.title.length > 120 || typeof rule.description !== 'string' || rule.description.length > 1000 || typeof rule.category !== 'string' || !rule.category.trim() || rule.category.length > 60 || !['critical','warning','low'].includes(rule.severity) || typeof rule.enabled !== 'boolean') return null;
      ids.add(rule.id);
    }
    const statuses: Record<number, ReviewStatus> = {};
    if (data.statuses && typeof data.statuses === 'object') {
      for (const [id, status] of Object.entries(data.statuses)) if (ids.has(Number(id)) && ['unseen','accepted','dismissed'].includes(status)) statuses[Number(id)] = status;
    }
    const minimumId = Math.max(20, ...ids) + 1;
    return { version: 2, rules: data.rules, nextRuleId: Number.isSafeInteger(data.nextRuleId) && data.nextRuleId! >= minimumId ? data.nextRuleId! : minimumId, projects, statuses };
  } catch { return null; }
}

export function initialWorkspace(): SavedWorkspace {
  return {version:2, rules:defaultRules, nextRuleId:21, projects:[createDemoProject()], statuses:{}};
}
