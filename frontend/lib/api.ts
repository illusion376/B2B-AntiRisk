import type {
  DocumentDto, FindingDto, FindingsDto, HistoryDto, PageDto, ProjectDto,
  ProjectFileDto, RuleDto, UploadDto, UserDto,
} from './api-types';
import type {
  CheckRule, DocumentInfo, Finding, HistoryEntry, OutlineSection, PageContent, Project,
  ProjectDraft, ProjectFile, ReportMode, ReviewStatus, RuleDraft, SearchResponse, UploadResult, User,
} from './types';
import { reportFilename, saveDownload } from './report';

export interface RequestOptions { signal?: AbortSignal }
export interface ReportOptions extends RequestOptions { mode?: string; format?: string; includeDismissed?: boolean }
export interface FindingUpdate { status?: ReviewStatus; reviewerComment?: string | null }
export interface HistoryOptions extends RequestOptions { limit?: number; offset?: number; actions?: string | string[] }

/** The default same-origin URL works through Next.js rewrites and Docker nginx. */
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || '/api').replace(/\/+$/, '');

export class ApiError extends Error {
  constructor(message: string, public readonly status: number = 0) {
    super(message);
    this.name = 'ApiError';
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось выполнить запрос. Попробуйте ещё раз.';
}

function apiUrl(path: string, params?: Record<string, string | number | boolean | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined) query.set(key, String(value));
  }
  return `${API_BASE}${path}${query.size ? `?${query}` : ''}`;
}
const segment = encodeURIComponent;

function serverMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const { detail } = body;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail.flatMap(item => {
        if (!item || typeof item !== 'object' || typeof item.msg !== 'string') return [];
        const path = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : '';
        return [path ? `${path}: ${item.msg}` : item.msg];
      });
      if (messages.length) return messages.join('; ');
    }
  }
  if (status === 401) return 'Необходима авторизация.';
  if (status === 403) return 'Недостаточно прав для этого действия.';
  if (status === 404) return 'Запрошенные данные не найдены.';
  if (status === 413) return 'Размер загружаемых файлов превышает ограничение сервера.';
  if (status >= 500) return 'Сервер временно недоступен. Попробуйте ещё раз.';
  return `Не удалось выполнить запрос (HTTP ${status}).`;
}

async function requestResponse(path: string, options: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: 'same-origin', cache: 'no-store', ...options });
  } catch (error) {
    if (options.signal?.aborted || (error instanceof Error && error.name === 'AbortError')) throw error;
    throw new ApiError('Не удалось связаться с сервером. Проверьте подключение и повторите попытку.');
  }
  if (!response.ok) {
    let body: unknown;
    try { body = await response.json(); } catch { /* Proxy error pages must not be shown as messages. */ }
    throw new ApiError(serverMessage(body, response.status), response.status);
  }
  return response;
}

async function request<TDto, T>(path: string, adapt: (value: TDto) => T, options: RequestInit = {}): Promise<T> {
  const response = await requestResponse(path, {
    ...options,
    headers: { Accept: 'application/json', ...options.headers },
  });
  let value: TDto;
  try { value = await response.json() as TDto; } catch {
    if (options.signal?.aborted) throw options.signal.reason;
    throw new ApiError('Сервер вернул некорректный ответ. Попробуйте ещё раз.', response.status);
  }
  try { return adapt(value); } catch {
    throw new ApiError('Формат данных сервера не соответствует приложению. Обновите страницу.', response.status);
  }
}

function json(body: unknown): Pick<RequestInit, 'body' | 'headers'> {
  return { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } };
}

function timestamp(value: string): number {
  const time = typeof value === 'string' ? Date.parse(value) : NaN;
  if (!Number.isFinite(time)) throw new Error('Invalid timestamp');
  return time;
}
function nullableTime(value: string | null): number | null { return value === null ? null : timestamp(value); }
function id(value: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Invalid identifier');
  return value;
}

export function mapDocument(value: DocumentDto): DocumentInfo {
  return {
    id: id(value.id), analysisId: id(value.analysis_id), name: value.file_name,
    relativePath: value.relative_path, type: value.file_type, size: value.file_size,
    status: value.status, phase: value.phase, label: value.label, progress: value.progress,
    totalPages: value.total_pages, isScanned: value.is_scanned, ocrPages: value.ocr_pages,
    ocrConfidence: value.ocr_confidence, lawType: value.law_type, riskScore: value.risk_score,
    trafficLight: value.traffic_light, counts: value.counts, rulesChecked: value.rules_checked,
    errorMessage: value.error_message, processingMs: value.processing_ms, hasPreview: value.has_preview,
    createdAt: timestamp(value.created_at), updatedAt: nullableTime(value.updated_at),
  };
}
export function mapProjectFile(value: ProjectFileDto): ProjectFile {
  return {
    id: id(value.id), name: value.name, type: value.type, size: value.size, addedAt: timestamp(value.added_at),
    status: value.status, phase: value.phase, label: value.label, progress: value.progress,
    errorMessage: value.error_message, riskScore: value.risk_score, trafficLight: value.traffic_light,
    counts: value.counts, rulesChecked: value.rules_checked, documents: value.documents.map(mapDocument),
  };
}
export function mapProject(value: ProjectDto): Project {
  return {
    id: id(value.id), title: value.title, description: value.description, files: value.files.map(mapProjectFile),
    createdAt: timestamp(value.created_at), updatedAt: timestamp(value.updated_at), processingCount: value.processing_count,
    counts: value.counts, trafficLight: value.traffic_light,
  };
}
export function mapFinding(value: FindingDto): Finding {
  return {
    id: id(value.id), number: value.number, documentId: id(value.document_id), ruleId: value.rule_id,
    title: value.title, description: value.description, severity: value.severity, category: value.category,
    clause: value.clause, page: value.page, quote: value.quote, recommendation: value.recommendation,
    comment: value.comment, legalReference: value.legal_reference, highlights: value.highlights,
    quoteVerified: value.quote_verified, confidence: value.confidence, source: value.source,
    status: value.status, reviewerComment: value.reviewer_comment, reviewedAt: nullableTime(value.reviewed_at),
    createdAt: timestamp(value.created_at),
  };
}
export function mapRule(value: RuleDto): CheckRule {
  return {
    id: id(value.id), title: value.title, description: value.description, category: value.category,
    severity: value.severity, enabled: value.enabled, lawType: value.law_type,
    semanticQuery: value.semantic_query, llmPrompt: value.llm_prompt, legalReference: value.legal_reference,
    sortOrder: value.sort_order, createdAt: timestamp(value.created_at), updatedAt: nullableTime(value.updated_at),
  };
}
export function mapPage(value: PageDto): PageContent {
  if (!Number.isInteger(value.page) || value.page < 1) throw new Error('Invalid page');
  return {
    page: value.page, totalPages: value.total_pages, width: value.width, height: value.height,
    isOcr: value.is_ocr, ocrConfidence: value.ocr_confidence,
    sections: value.sections.map(section => ({
      title: section.title,
      paragraphs: section.paragraphs.map(paragraph => ({ clause: paragraph.clause, text: paragraph.text, findingIds: paragraph.finding_ids.map(id) })),
    })),
  };
}
export function mapUser(value: UserDto): User {
  return { id: id(value.id), email: value.email, fullName: value.full_name, companyName: value.company_name, role: value.role, initials: value.initials };
}
export function mapHistory(value: HistoryDto): HistoryEntry {
  timestamp(value.time);
  return { id: id(value.id), action: value.action, title: value.title, detail: value.detail, time: value.time, entityType: value.entity_type, entityId: value.entity_id };
}

/** Omitted fields must stay omitted: the backend updates generated prompts after a basic edit. */
export function rulePayload(draft: Partial<RuleDraft>) {
  return {
    title: draft.title, description: draft.description, category: draft.category, severity: draft.severity,
    enabled: draft.enabled, law_type: draft.lawType, semantic_query: draft.semanticQuery, llm_prompt: draft.llmPrompt,
    legal_reference: draft.legalReference, sort_order: draft.sortOrder,
  };
}

export function thumbnailUrl(documentId: string, page: number, width = 160): string {
  return apiUrl(`/documents/${segment(documentId)}/pages/${page}/thumbnail`, { width });
}
export function documentFileUrl(documentId: string): string { return apiUrl(`/documents/${segment(documentId)}/file`); }
export function documentOriginalUrl(documentId: string): string { return apiUrl(`/documents/${segment(documentId)}/original`); }

export const api = {
  getProjects: (options: RequestOptions = {}): Promise<Project[]> => request<ProjectDto[], Project[]>('/projects', values => values.map(mapProject), options),
  getProject: (projectId: string, options: RequestOptions = {}): Promise<Project> => request(`/projects/${segment(projectId)}`, mapProject, options),
  createProject: (draft: ProjectDraft, options: RequestOptions = {}): Promise<Project> => request('/projects', mapProject, { ...options, method: 'POST', ...json(draft) }),
  uploadFiles: (projectId: string, files: File[], options: RequestOptions & { lawType?: 'AUTO' | '44-FZ' | '223-FZ' } = {}): Promise<UploadResult> => {
    const body = new FormData();
    for (const file of files) body.append('files', file);
    body.append('law_type', options.lawType ?? 'AUTO');
    return request<UploadDto, UploadResult>(`/projects/${segment(projectId)}/files`, value => ({ files: value.files.map(mapProjectFile), errors: value.errors }), { signal: options.signal, method: 'POST', body });
  },
  getDocument: (documentId: string, options: RequestOptions = {}): Promise<DocumentInfo> => request(`/documents/${segment(documentId)}`, mapDocument, options),
  getPage: (documentId: string, page: number, options: RequestOptions = {}): Promise<PageContent> => request(`/documents/${segment(documentId)}/pages/${page}`, mapPage, options),
  getFindings: (documentId: string, options: RequestOptions = {}): Promise<Finding[]> => request<FindingsDto, Finding[]>(`/documents/${segment(documentId)}/findings`, value => value.groups.flatMap(group => group.items.map(mapFinding)), options),
  getOutline: (documentId: string, options: RequestOptions = {}): Promise<OutlineSection[]> => request<OutlineSection[], OutlineSection[]>(`/documents/${segment(documentId)}/outline`, values => values.map(value => ({ title: value.title, page: value.page, clauses: value.clauses })), options),
  searchDocument: (documentId: string, query: string, options: RequestOptions = {}): Promise<SearchResponse> => request<SearchResponse, SearchResponse>(`/documents/${segment(documentId)}/search?${new URLSearchParams({ q: query })}`, value => {
    if (!Array.isArray(value.hits) || typeof value.query !== 'string' || !Number.isInteger(value.total)) throw new Error('Invalid search response');
    return value;
  }, options),
  updateFinding: (findingId: string, update: FindingUpdate, options: RequestOptions = {}): Promise<Finding> => request(`/findings/${segment(findingId)}`, mapFinding, { ...options, method: 'PATCH', ...json({ status: update.status, reviewer_comment: update.reviewerComment }) }),
  renameDocument: (documentId: string, name: string, options: RequestOptions = {}): Promise<DocumentInfo> => request(`/documents/${segment(documentId)}`, mapDocument, { ...options, method: 'PATCH', ...json({ file_name: name }) }),
  getRules: (options: RequestOptions = {}): Promise<CheckRule[]> => request<RuleDto[], CheckRule[]>('/rules', values => values.map(mapRule), options),
  createRule: (draft: RuleDraft, options: RequestOptions = {}): Promise<CheckRule> => request('/rules', mapRule, { ...options, method: 'POST', ...json(rulePayload(draft)) }),
  updateRule: (ruleId: string, draft: Partial<RuleDraft>, options: RequestOptions = {}): Promise<CheckRule> => request(`/rules/${segment(ruleId)}`, mapRule, { ...options, method: 'PATCH', ...json(rulePayload(draft)) }),
  deleteRule: async (ruleId: string, options: RequestOptions = {}): Promise<void> => { await requestResponse(`/rules/${segment(ruleId)}`, { ...options, method: 'DELETE' }); },
  getHistory: (options: HistoryOptions = {}): Promise<HistoryEntry[]> => {
    const query = new URLSearchParams({ limit: String(options.limit ?? 100), offset: String(options.offset ?? 0) });
    if (options.actions) query.set('actions', Array.isArray(options.actions) ? options.actions.join(',') : options.actions);
    return request<HistoryDto[], HistoryEntry[]>(`/history?${query}`, values => values.map(mapHistory), { signal: options.signal });
  },
  getUser: (options: RequestOptions = {}): Promise<User> => request('/users/me', mapUser, options),
  getReportModes: (options: RequestOptions = {}): Promise<ReportMode[]> => request<ReportMode[], ReportMode[]>('/reports/modes', values => values.map(value => {
    if (typeof value.id !== 'string' || typeof value.title !== 'string' || !Array.isArray(value.formats)) throw new Error('Invalid report mode');
    return value;
  }), options),
  downloadReport: async (documentId: string, options: ReportOptions = {}): Promise<void> => {
    const mode = options.mode ?? 'detailed';
    const format = mode === 'annotated' ? 'pdf' : options.format ?? 'docx';
    const query = new URLSearchParams({ mode, format, include_dismissed: String(options.includeDismissed ?? false) });
    const response = await requestResponse(`/documents/${segment(documentId)}/report?${query}`, { signal: options.signal });
    const blob = await response.blob();
    saveDownload(blob, reportFilename(response.headers.get('Content-Disposition'), `report.${format}`));
  },
  rerunProject: (projectId: string, options: RequestOptions & { ruleIds?: string[] } = {}): Promise<{ documents: number }> => request<{ documents: number }, { documents: number }>(`/projects/${segment(projectId)}/rerun`, value => {
    if (!Number.isInteger(value.documents) || value.documents < 0) throw new Error('Invalid rerun response');
    return value;
  }, { signal: options.signal, method: 'POST', ...json({ rule_ids: options.ruleIds }) }),
  reanalyzeDocument: (documentId: string, options: RequestOptions = {}): Promise<DocumentInfo> => request(`/documents/${segment(documentId)}/reanalyze`, mapDocument, { ...options, method: 'POST' }),
  thumbnailUrl,
  documentFileUrl,
  documentOriginalUrl,
};
