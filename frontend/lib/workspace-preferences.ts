import type { AnalysisSensitivity, Severity } from './types';

export const preferenceKey = 'b2b-antirisk.workspace-preferences.v1';
export const displaySeverities = ['critical', 'warning', 'low', 'ok'] as const;
export type DisplaySeverity = typeof displaySeverities[number];
export type NoticeKind = 'completed' | 'error' | 'critical';
export interface WorkspacePreferences {
  defaultSeverities: DisplaySeverity[];
  sensitivity: AnalysisSensitivity;
  notifications: Record<NoticeKind, boolean> & { desktop: boolean };
}
export const sensitivityOptions: { id: AnalysisSensitivity; label: string; description: string }[] = [
  { id: 'strict', label: 'Только явные', description: 'Меньше предположений, больше внимания к явно выраженным условиям.' },
  { id: 'balanced', label: 'Сбалансированная', description: 'Явные и обоснованные потенциальные риски.' },
  { id: 'sensitive', label: 'Повышенная', description: 'Дополнительное внимание к неоднозначным условиям и возможным рискам.' },
];

export function defaultPreferences(): WorkspacePreferences {
  return { defaultSeverities: [...displaySeverities], sensitivity: 'balanced',
    notifications: { completed: true, error: true, critical: true, desktop: false } };
}

export function normalizePreferences(value: unknown): WorkspacePreferences {
  const fallback = defaultPreferences();
  if (!value || typeof value !== 'object') return fallback;
  const input = value as Partial<WorkspacePreferences>;
  const levels = Array.isArray(input.defaultSeverities)
    ? displaySeverities.filter(level => input.defaultSeverities!.includes(level)) : [];
  const notifications = input.notifications;
  return {
    defaultSeverities: levels.length ? levels : fallback.defaultSeverities,
    sensitivity: sensitivityOptions.some(option => option.id === input.sensitivity) ? input.sensitivity! : 'balanced',
    notifications: {
      completed: typeof notifications?.completed === 'boolean' ? notifications.completed : true,
      error: typeof notifications?.error === 'boolean' ? notifications.error : true,
      critical: typeof notifications?.critical === 'boolean' ? notifications.critical : true,
      desktop: typeof notifications?.desktop === 'boolean' ? notifications.desktop : false,
    },
  };
}

export function parsePreferences(raw: string | null): WorkspacePreferences {
  try { return normalizePreferences(raw ? JSON.parse(raw) : null); }
  catch { return defaultPreferences(); }
}

export function matchesSeverity(severity: Severity, filter: string, defaults: readonly DisplaySeverity[]): boolean {
  return filter === 'all' || (filter === 'default' ? defaults.some(value => value === severity) : severity === filter);
}
