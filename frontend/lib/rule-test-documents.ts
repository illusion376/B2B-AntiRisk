import { fileType, SUPPORTED_FILE_TYPES, validateUpload } from './projects';
import type { DocumentInfo, Project } from './types';

export interface RuleTestTargetDocument {
  id: string;
  name: string;
  projectTitle?: string;
  isTest?: boolean;
  status: string;
  progress: number;
  phase?: string;
  errorMessage?: string | null;
}

export const RULE_TEST_UPLOAD_ACCEPT = SUPPORTED_FILE_TYPES
  .filter(type => type !== 'zip').map(type => `.${type}`).join(',');

export function validateRuleTestUpload(file: Pick<File, 'name' | 'size'>): string | null {
  if (fileType(file.name) === 'zip') return 'Выберите отдельный документ. ZIP-архивы для проверки правила не поддерживаются.';
  if (!fileType(file.name)) return 'Поддерживаются PDF, TXT, DOCX, DOC, RTF, ODT и изображения PNG, JPEG, TIFF, BMP.';
  return validateUpload(file, []);
}

export function asRuleTestDocument(document: DocumentInfo): RuleTestTargetDocument {
  return {
    id: document.id, name: document.name, isTest: true,
    status: document.status, progress: document.progress, phase: document.phase, errorMessage: document.errorMessage,
  };
}

export function projectRuleTestDocuments(project: Project): RuleTestTargetDocument[] {
  return project.isRuleTest ? project.files.flatMap(file => file.documents.map(asRuleTestDocument)) : [];
}

export function mergeRuleTestDocuments(
  testDocuments: RuleTestTargetDocument[], documents: RuleTestTargetDocument[],
): RuleTestTargetDocument[] {
  const unique = new Map<string, RuleTestTargetDocument>();
  for (const document of [...testDocuments, ...documents]) {
    if (!unique.has(document.id)) unique.set(document.id, document);
  }
  return [...unique.values()].sort((left, right) => Number(Boolean(right.isTest)) - Number(Boolean(left.isTest)));
}

export function isRuleTestDocumentReady(document: RuleTestTargetDocument): boolean {
  return document.phase === 'ready' || (!document.phase && document.status === 'COMPLETED');
}

export function isRuleTestDocumentProcessing(document: RuleTestTargetDocument): boolean {
  return document.phase === 'queued' || document.phase === 'processing';
}

export function ruleTestDocumentLabel(document: RuleTestTargetDocument): string {
  const name = document.isTest ? `[Тест] ${document.name}`
    : `${document.projectTitle ? `${document.projectTitle} / ` : ''}${document.name}`;
  if (isRuleTestDocumentReady(document)) return `${name} ✓`;
  if (document.phase === 'failed' || document.status === 'FAILED') return `${name} (ошибка подготовки)`;
  if (document.phase === 'unsupported' || document.status === 'UNSUPPORTED') return `${name} (формат не поддерживается)`;
  if (document.phase === 'uploaded' || document.status === 'UPLOADED') return `${name} (ожидает запуска)`;
  return `${name} (подготовка ${document.progress}%)`;
}

export function ruleTestDocumentWarning(document: RuleTestTargetDocument): string | null {
  if (isRuleTestDocumentReady(document)) return null;
  if (document.errorMessage) return document.errorMessage;
  if (document.phase === 'failed' || document.status === 'FAILED') return 'Не удалось подготовить документ. Загрузите его ещё раз или выберите другой.';
  if (document.phase === 'unsupported' || document.status === 'UNSUPPORTED') return 'Формат документа не поддерживается. Выберите другой файл.';
  if (document.phase === 'uploaded' || document.status === 'UPLOADED') return 'Документ ожидает запуска обработки. Выберите готовый документ или загрузите тестовый файл.';
  return `Документ готовится к проверке (${document.progress}%). Дождитесь завершения подготовки или выберите готовый документ.`;
}
