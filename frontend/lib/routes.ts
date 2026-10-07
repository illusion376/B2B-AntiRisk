import { DEMO_PROJECT_ID } from './projects';
import type { View } from './types';

/**
 * Hash-маршруты рабочего пространства. Работают на статическом хостинге (output: 'export'):
 *   #/documents                                   — все проекты
 *   #/projects/<id>                               — файлы проекта
 *   #/projects/<id>/document?page=18&finding=1    — просмотр документа
 *   #/rules, #/history
 */
export interface WorkspaceRoute {
  view: View;
  projectId: string;
  page: number;
  findingId: number | null;
}

export const DEFAULT_ROUTE: WorkspaceRoute = { view: 'documents', projectId: DEMO_PROJECT_ID, page: 18, findingId: 1 };

const MAX_PROJECT_ID = 100;

function positiveInteger(value: string | null): number | null {
  if (value === null || !/^\d{1,9}$/.test(value)) return null;
  const number = Number(value);
  return number >= 1 ? number : null;
}

function decodeSegment(segment: string): string | null {
  try {
    const value = decodeURIComponent(segment);
    return value.trim() && value.length <= MAX_PROJECT_ID ? value : null;
  } catch {
    return null; // битая percent-кодировка
  }
}

/** Ограничивает страницу диапазоном документа и убирает некорректные значения. */
export function normalizeRoute(route: WorkspaceRoute, totalPages: number): WorkspaceRoute {
  const page = Number.isFinite(route.page) ? Math.min(totalPages, Math.max(1, Math.round(route.page))) : DEFAULT_ROUTE.page;
  const findingId = route.findingId !== null && Number.isSafeInteger(route.findingId) && route.findingId > 0 ? route.findingId : null;
  return { ...route, page, findingId };
}

/**
 * Разбирает location.hash. Для «#/rules» и «#/history» проект, страница и замечание берутся
 * из previous — как раньше, когда они хранились в состоянии и не терялись при переходе по вкладкам.
 */
export function parseRoute(hash: string, totalPages: number, previous: WorkspaceRoute = DEFAULT_ROUTE): WorkspaceRoute {
  const raw = hash.replace(/^#/, '');
  const [path, query = ''] = raw.split('?', 2);
  const segments = path.split('/').filter(Boolean);
  const params = new URLSearchParams(query);

  const first = segments[0];
  if (segments.length === 1 && (first === 'rules' || first === 'history' || first === 'documents')) {
    return { ...previous, view: first };
  }
  if (segments[0] === 'projects' && (segments.length === 2 || (segments.length === 3 && segments[2] === 'document'))) {
    const projectId = decodeSegment(segments[1]);
    if (projectId === null) return { ...previous, view: 'documents' };
    if (segments.length === 2) return { ...previous, view: 'project', projectId };
    const page = positiveInteger(params.get('page'));
    return normalizeRoute({
      view: 'document',
      projectId,
      page: page ?? DEFAULT_ROUTE.page,
      findingId: positiveInteger(params.get('finding')),
    }, totalPages);
  }
  // Пустой или неизвестный адрес — список проектов
  return { ...previous, view: 'documents' };
}

export function formatRoute(route: WorkspaceRoute): string {
  const project = `#/projects/${encodeURIComponent(route.projectId)}`;
  switch (route.view) {
    case 'project':
      return project;
    case 'document': {
      const params = new URLSearchParams({ page: String(route.page) });
      if (route.findingId !== null) params.set('finding', String(route.findingId));
      return `${project}/document?${params}`;
    }
    default:
      return `#/${route.view}`;
  }
}
