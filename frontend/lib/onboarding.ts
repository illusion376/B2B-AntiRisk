import type { Project } from './types';

export type DocumentTourStage = 'findings' | 'assistant';

export interface OnboardingProgress {
  workspaceDone: boolean;
  projectDone: boolean;
  projectId: string | null;
  documentStep: DocumentTourStage;
}

export const emptyOnboarding: OnboardingProgress = { workspaceDone: false, projectDone: false, projectId: null, documentStep: 'findings' };
export const onboardingKey = (userId: string) => `antirisk:onboarding:v1:${encodeURIComponent(userId)}`;

export function parseOnboarding(raw: string | null): OnboardingProgress {
  try {
    const value = JSON.parse(raw ?? 'null');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return { ...emptyOnboarding };
    const projectDone = value.projectDone === true;
    return {
      workspaceDone: value.workspaceDone === true,
      projectDone,
      projectId: !projectDone && typeof value.projectId === 'string' && value.projectId.trim()
        && value.projectId.length <= 200 && !/[\u0000-\u001f\u007f]/.test(value.projectId) ? value.projectId : null,
      documentStep: !projectDone && value.documentStep === 'assistant' ? 'assistant' : 'findings',
    };
  } catch { return { ...emptyOnboarding }; }
}

export type ProjectTourStage = 'upload' | 'start' | 'waiting' | 'open' | 'failed' | 'unavailable';

/** Only server state can advance the project guide; an elapsed timer is never a result. */
export function projectTourStage(project: Project): ProjectTourStage {
  if (!project.files.length) return 'upload';
  const items = project.files.flatMap(file => [file, ...file.documents]);
  if (project.processingCount > 0 || items.some(item => item.phase === 'queued' || item.phase === 'processing')) return 'waiting';
  if (items.some(item => item.phase === 'uploaded')) return 'start';
  if (project.files.some(file => file.documents.some(document => document.phase === 'ready' && document.hasPreview))) return 'open';
  if (items.some(item => item.phase === 'failed' || item.phase === 'unsupported')) return 'failed';
  return 'unavailable';
}

export interface TourStep {
  id: string;
  title: string;
  description: string;
  target: string;
  fallback?: string;
  number: number;
  total: number;
  action: string;
  waiting?: boolean;
  placement?: 'right';
}

export const workspaceTour: TourStep[] = [
  { id: 'new-project', title: 'Новый проект', description: 'Начните с создания проекта: укажите название и объедините в нём документы одной сделки.', target: '[data-onboarding="new-project"]', number: 1, total: 4, action: 'Далее', placement: 'right' },
  { id: 'projects', title: 'Проекты', description: 'Здесь находятся ваши проекты. Открывайте документы, следите за обработкой и возвращайтесь к результатам проверки.', target: '[data-onboarding="nav-documents"]', number: 2, total: 4, action: 'Далее', placement: 'right' },
  { id: 'rules', title: 'Правила проекта', description: 'Подготовьте правила проверки: добавьте свои условия, выберите степень риска и включите нужные правила для анализа.', target: '[data-onboarding="nav-rules"]', number: 3, total: 4, action: 'Далее', placement: 'right' },
  { id: 'settings', title: 'Настройки', description: 'Выберите режим и чувствительность анализа, настройте уведомления и укажите данные для итогового отчёта.', target: '[data-onboarding="nav-settings"]', number: 4, total: 4, action: 'Готово', placement: 'right' },
];

export function projectTourStep(project: Project): TourStep {
  const stage = projectTourStage(project);
  const common = { id: `project-${stage}`, total: 5, fallback: '[data-onboarding="project-files"]' };
  switch (stage) {
    case 'upload': return { ...common, number: 1, title: 'Выберите файлы', description: 'Добавьте документы в проект с устройства или перетащите их в область загрузки. Можно загрузить несколько файлов или ZIP-архив.', target: '[data-onboarding="upload-files"]', action: 'Выбрать файлы' };
    case 'start': return { ...common, number: 2, title: 'Начните анализ', description: 'Файлы загружены. Нажмите «Начать анализ», чтобы проверить их по включённым правилам. Если режим недоступен, его можно изменить в настройках.', target: '[data-onboarding="start-analysis"]', action: 'Начать анализ' };
    case 'waiting': return { ...common, number: 3, title: 'Дождитесь завершения анализа', description: 'Документы обрабатываются. Когда проверка завершится, здесь появится кнопка открытия результата. Подсказка обновится автоматически.', target: '[data-onboarding="analysis-progress"]', action: 'Идёт анализ…', waiting: true };
    case 'open': return { ...common, number: 3, title: 'Откройте проверенный документ', description: 'Результат готов. Откройте документ, чтобы увидеть замечания рядом с текстом, задать вопрос ИИ-помощнику и скачать отчёт.', target: '[data-onboarding="open-document"]', action: 'Открыть документ' };
    case 'failed': return { ...common, number: 2, title: 'Повторите проверку', description: 'Обработка завершилась с ошибкой. Посмотрите сообщение рядом с файлом и повторите анализ. Если повтор недоступен, добавьте другой документ.', target: '[data-onboarding="start-analysis"]', fallback: '[data-onboarding="upload-files"]', action: 'Продолжить' };
    case 'unavailable': return { ...common, number: 3, title: 'Проверьте результат обработки', description: 'Обработка завершена, но сервер не предоставил документ с доступным предпросмотром. Посмотрите сообщение рядом с файлом или добавьте другой документ.', target: '[data-onboarding="project-files"]', action: 'Предпросмотр недоступен', waiting: true };
  }
}

export const documentTour: Record<DocumentTourStage, TourStep> = {
  findings: { id: 'document-findings', number: 4, total: 5, title: 'Замечания по документу', description: 'В «Результатах» замечания сгруппированы по уровню риска. Нажмите на замечание, чтобы перейти к его странице. Кнопка «⋮» открывает обоснование и рекомендации. В столбце «Статус проверки» можно принять или отклонить замечание.', target: '[data-onboarding="document-findings"]', action: 'Далее' },
  assistant: { id: 'document-assistant', number: 5, total: 5, title: 'ИИ-помощник', description: 'Помощник отвечает по документу и результатам проверки. Чтобы задать вопрос по конкретному замечанию, нажмите значок чата в его строке. Здесь же можно попросить подготовить итоговый документ.', target: '[data-onboarding="document-assistant"]', action: 'Готово' },
};
