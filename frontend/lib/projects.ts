import type { ProcessingState, ProjectFile } from './types';

export const MAX_FILE_BYTES = 100 * 1024 * 1024;
export const SUPPORTED_FILE_TYPES = ['pdf', 'txt', 'zip', 'rar', '7z', 'docx', 'doc', 'rtf', 'odt', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp'] as const;
export const ARCHIVE_FILE_TYPES: readonly string[] = ['zip', 'rar', '7z'];
export const UPLOAD_ACCEPT = SUPPORTED_FILE_TYPES.map(type => `.${type}`).join(',');

export function fileType(name: string): string | null {
  const extension = name.split('.').pop()?.toLowerCase();
  return extension && (SUPPORTED_FILE_TYPES as readonly string[]).includes(extension) ? extension : null;
}

export function validateUpload(file: Pick<File, 'name' | 'size'>, existing: ProjectFile[]): string | null {
  if (!fileType(file.name)) return 'Поддерживаются PDF, DOCX, DOC, RTF, ODT, TXT, изображения PNG, JPEG, TIFF, BMP и архивы ZIP, RAR, 7Z.';
  if (!file.name.trim() || file.name.length > 255) return 'Название файла должно содержать от 1 до 255 символов.';
  if (file.size === 0) return 'Файл пустой. Выберите файл с содержимым.';
  if (file.size > MAX_FILE_BYTES) return 'Размер файла превышает 100 МБ.';
  if (existing.some(item => item.name === file.name && item.size === file.size)) return 'Этот файл уже добавлен в проект.';
  return null;
}

/** Processing state always comes from the server; time cannot complete an analysis. */
export function getProcessing(file: ProcessingState, _now?: number) {
  return { phase: file.phase, progress: file.progress, label: file.label };
}

export function formatFileSize(bytes: number | null) {
  if (bytes === null) return '—';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

export function formatProjectDate(timestamp: number) {
  return new Date(timestamp).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Tomsk' });
}
