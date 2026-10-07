import { DEMO_PROJECT_ID } from './projects';
import type { View } from './types';

export interface WorkspaceRoute {
  view: View;
  projectId: string;
  page: number;
  findingId: number | null;
}

export const defaultRoute: WorkspaceRoute = {
  view: 'documents', projectId: DEMO_PROJECT_ID, page: 18, findingId: 1,
};

export function normalizeRoute(route: WorkspaceRoute, totalPages: number): WorkspaceRoute {
  const view = ['documents', 'project', 'document', 'rules', 'history'].includes(route.view) ? route.view : 'documents';
  return {
    view,
    projectId: route.projectId.trim() || DEMO_PROJECT_ID,
    page: Math.max(1, Math.min(totalPages, Number.isFinite(route.page) ? Math.trunc(route.page) : 18)),
    findingId: Number.isSafeInteger(route.findingId) && route.findingId! > 0 ? route.findingId : null,
  };
}

export function parseRoute(hash: string, totalPages: number): WorkspaceRoute {
  if (!hash || hash === '#') return { ...defaultRoute };
  const [view, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const params = new URLSearchParams(query);
  return normalizeRoute({
    view: view as View,
    projectId: params.get('project') ?? DEMO_PROJECT_ID,
    page: params.has('page') ? Number(params.get('page')) : 18,
    findingId: params.has('finding') ? Number(params.get('finding')) : null,
  }, totalPages);
}

export function serializeRoute(route: WorkspaceRoute): string {
  const params = new URLSearchParams();
  if (route.view === 'project' || route.view === 'document') params.set('project', route.projectId);
  if (route.view === 'document') {
    params.set('page', String(route.page));
    if (route.findingId !== null) params.set('finding', String(route.findingId));
  }
  const query = params.toString();
  return `#${route.view}${query ? `?${query}` : ''}`;
}
