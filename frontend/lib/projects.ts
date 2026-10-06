import { documentInfo } from './mock-data';
import type { Project, ProjectFile } from './types';

export const DEMO_PROJECT_ID = 'contract-project';
export const DEMO_FILE_ID = 'contract-demo';
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
export const PROCESSING_DURATION = 6000;

export function createDemoProject(name = documentInfo.name): Project {
  const addedAt = Date.UTC(2026, 9, 4, 12, 36);
  return { id: DEMO_PROJECT_ID, title: 'Проект контракта', description: 'Проверка условий и обязательств по контракту.', updatedAt: addedAt,
    files: [{id: DEMO_FILE_ID, name, type: 'pdf', size: 0, source: 'demo', addedAt}] };
}

export function fileType(name: string): ProjectFile['type'] | null {
  const extension = name.split('.').pop()?.toLowerCase();
  return extension === 'pdf' || extension === 'txt' || extension === 'zip' ? extension : null;
}

export function validateUpload(file: Pick<File, 'name' | 'size'>, existing: ProjectFile[]): string | null {
  if (!fileType(file.name)) return 'Поддерживаются только PDF, TXT и ZIP.';
  if (!file.name.trim() || file.name.length > 255) return 'Название файла должно содержать от 1 до 255 символов.';
  if (file.size === 0) return 'Файл пустой. Выберите файл с содержимым.';
  if (file.size > MAX_FILE_BYTES) return 'Размер файла превышает 50 МБ.';
  if (existing.some(item => item.name === file.name && item.size === file.size)) return 'Этот файл уже добавлен в проект.';
  return null;
}

export function getProcessing(file: ProjectFile, now: number) {
  if (file.source === 'demo') return {phase: 'ready' as const, progress: 100, label: 'Демонстрационный документ'};
  const elapsed = Math.max(0, now - file.addedAt);
  if (elapsed < 900) return {phase: 'queued' as const, progress: 0, label: 'В очереди'};
  if (elapsed < PROCESSING_DURATION) return {phase: 'processing' as const, progress: Math.min(95, Math.round(elapsed / PROCESSING_DURATION * 100)), label: 'Обрабатывается'};
  return {phase: 'ready' as const, progress: 100, label: 'Обработано · демо'};
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

export function formatProjectDate(timestamp: number) {
  return new Date(timestamp).toLocaleDateString('ru-RU', {day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Tomsk'});
}

/** Accept only metadata; uploaded file contents never enter localStorage. */
export function parseProjects(value: unknown): Project[] | null {
  if (!Array.isArray(value) || !value.length) return null;
  const projectIds = new Set<string>();
  const fileIds = new Set<string>();
  const text = (v: unknown, max: number, required = true): v is string => typeof v === 'string' && v.length <= max && (!required || !!v.trim());
  const time = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0 && v <= 8640000000000000;
  const projects: Project[] = [];
  for (const project of value) {
    if (!project || !text(project.id, 100) || projectIds.has(project.id) || !text(project.title, 120) || !text(project.description, 1000, false) || !time(project.updatedAt) || !Array.isArray(project.files)) return null;
    projectIds.add(project.id);
    const files: ProjectFile[] = [];
    for (const file of project.files) {
      if (!file || !text(file.id, 100) || fileIds.has(file.id) || !text(file.name, 255) || !['pdf','txt','zip'].includes(file.type) || fileType(file.name) !== file.type || !Number.isSafeInteger(file.size) || file.size < 0 || file.size > MAX_FILE_BYTES || !['demo','upload'].includes(file.source) || !time(file.addedAt)) return null;
      if (file.source === 'demo' && (project.id !== DEMO_PROJECT_ID || file.id !== DEMO_FILE_ID || file.type !== 'pdf')) return null;
      if (file.source === 'upload' && (file.size === 0 || file.id === DEMO_FILE_ID)) return null;
      fileIds.add(file.id);
      files.push({id:file.id,name:file.name,type:file.type,size:file.size,source:file.source,addedAt:file.addedAt});
    }
    projects.push({id:project.id,title:project.title,description:project.description,updatedAt:project.updatedAt,files});
  }
  if (!projects.some(project => project.id === DEMO_PROJECT_ID && project.files.some(file => file.id === DEMO_FILE_ID && file.source === 'demo'))) return null;
  return projects;
}
