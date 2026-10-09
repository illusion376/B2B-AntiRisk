import type { ProcessingPhase, Project } from './types';
import type { NoticeKind } from './workspace-preferences';

interface FileSnapshot {
  phase: ProcessingPhase;
  error: string | null;
  critical: number;
  name: string;
  projectId: string;
  projectTitle: string;
  documentId: string | null;
}
export type AnalysisSnapshot = Map<string, FileSnapshot>;
export interface AnalysisNotice {
  id: string;
  kind: NoticeKind;
  title: string;
  body: string;
  projectId: string;
  fileId: string;
  documentId: string | null;
  createdAt: number;
  read: boolean;
}

export function analysisSnapshot(projects: Project[]): AnalysisSnapshot {
  return new Map(projects.flatMap(project => project.files.map(file => {
    const errors = file.documents.filter(document => document.phase === 'failed' || document.errorMessage);
    const error = file.errorMessage || errors.map(document => document.errorMessage || `${document.name}: ошибка проверки`).join('; ')
      || (file.phase === 'failed' ? 'Не удалось выполнить анализ.' : null);
    const document = file.documents.find(document => document.phase === 'ready' && document.counts.critical > 0)
      ?? (file.documents.length === 1 && file.documents[0].phase === 'ready' ? file.documents[0] : null);
    return [file.id, { phase: file.phase, error, critical: file.counts.critical, name: file.name,
      projectId: project.id, projectTitle: project.title, documentId: document?.id ?? null }] as const;
  })));
}

export function analysisEvents(previous: AnalysisSnapshot, current: AnalysisSnapshot, now = Date.now()): AnalysisNotice[] {
  const notices: AnalysisNotice[] = [];
  for (const [fileId, file] of current) {
    const before = previous.get(fileId);
    if (!before) continue; // Не сообщаем о старых результатах при открытии сайта.
    const wasRunning = before.phase === 'uploaded' || before.phase === 'queued' || before.phase === 'processing';
    const finished = file.phase === 'ready' || file.phase === 'failed';
    const push = (kind: NoticeKind, title: string, body: string) => notices.push({
      id: `${fileId}:${kind}:${now}`, kind, title, body, projectId: file.projectId, fileId,
      documentId: file.documentId, createdAt: now, read: false,
    });
    if (finished && file.error && (wasRunning || file.error !== before.error)) {
      push('error', 'Ошибка анализа', `${file.name} · ${file.projectTitle}. ${file.error}`);
    }
    if (wasRunning && file.phase === 'ready' && !file.error) {
      push('completed', 'Анализ завершён', `${file.name} · ${file.projectTitle}`);
    }
    if (wasRunning && file.phase === 'ready' && file.critical > 0) {
      push('critical', 'Критические риски в документе', `${file.name}: ${file.critical} · ${file.projectTitle}`);
    }
  }
  return notices;
}
