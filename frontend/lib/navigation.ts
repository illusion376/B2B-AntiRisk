import type { View } from './types';

export interface WorkspaceRoute {
  view: View;
  projectId: string;
  documentId: string | null;
  page: number;
  findingId: string | null;
}

export const defaultRoute: WorkspaceRoute = {
  view: 'documents', projectId: '', documentId: null, page: 1, findingId: null,
};

// Identifiers are opaque server values, never array positions or demo constants.
function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const id = value.trim();
  if (!id || id.length > 200 || /[\u0000-\u001f\u007f]/.test(id)) return null;
  try { encodeURIComponent(id); } catch { return null; }
  return id;
}

export function normalizeRoute(route: WorkspaceRoute, totalPages?: number): WorkspaceRoute {
  const projectId = identifier(route.projectId) ?? '';
  const documentId = identifier(route.documentId);
  const view = ['documents', 'project', 'document', 'rules', 'history'].includes(route.view) ? route.view : 'documents';
  if (view === 'document' && projectId && documentId) {
    let page = Number.isFinite(route.page) ? Math.max(1, Math.min(Number.MAX_SAFE_INTEGER, Math.trunc(route.page))) : 1;
    // A direct link must keep its requested page until the document has loaded.
    if (totalPages !== undefined && Number.isFinite(totalPages) && totalPages > 0) page = Math.min(page, Math.max(1, Math.trunc(totalPages)));
    return { view, projectId, documentId, page, findingId: identifier(route.findingId) };
  }
  if ((view === 'project' || view === 'document') && projectId) return { ...defaultRoute, view: 'project', projectId };
  return { ...defaultRoute, view: view === 'rules' || view === 'history' ? view : 'documents' };
}

export function parseRoute(hash: string, totalPages?: number): WorkspaceRoute {
  const raw = hash.replace(/^#/, '');
  const separator = raw.indexOf('?');
  const path = separator < 0 ? raw : raw.slice(0, separator);
  const query = separator < 0 ? '' : raw.slice(separator + 1);
  let segments: string[];
  try {
    // Reject broken percent encoding rather than requesting a corrupted identifier.
    decodeURIComponent(query);
    segments = path.replace(/^\//, '').split('/').map(segment => decodeURIComponent(segment));
  } catch { return { ...defaultRoute }; }
  const params = new URLSearchParams(query);
  const rawPage = params.get('page');
  const page = rawPage !== null && /^\d+$/.test(rawPage) ? Number(rawPage) : 1;
  let route: WorkspaceRoute = { ...defaultRoute };
  if (segments.length === 1 && ['documents', 'rules', 'history'].includes(segments[0])) {
    route.view = segments[0] as View;
  } else if (segments[0] === 'projects' && segments.length === 2) {
    route = { ...route, view: 'project', projectId: segments[1] };
  } else if (segments[0] === 'projects' && segments.length === 4 && segments[2] === 'documents') {
    route = { view: 'document', projectId: segments[1], documentId: segments[3], page, findingId: params.get('finding') };
  } else if (segments.length === 1 && (segments[0] === 'project' || segments[0] === 'document')) {
    // Compatibility with develop links, provided they identify a real document.
    route = { view: segments[0], projectId: params.get('project') ?? '', documentId: params.get('document'), page, findingId: params.get('finding') };
  }
  return normalizeRoute(route, totalPages);
}

export function serializeRoute(route: WorkspaceRoute): string {
  const normalized = normalizeRoute(route);
  if (normalized.view !== 'project' && normalized.view !== 'document') return `#/${normalized.view}`;
  const projectPath = `#/projects/${encodeURIComponent(normalized.projectId)}`;
  if (normalized.view === 'project') return projectPath;
  const params = new URLSearchParams({ page: String(normalized.page) });
  if (normalized.findingId !== null) params.set('finding', normalized.findingId);
  return `${projectPath}/documents/${encodeURIComponent(normalized.documentId!)}?${params}`;
}
