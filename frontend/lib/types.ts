export type Severity = 'critical' | 'warning' | 'low' | 'ok';
export type RiskLevel = Exclude<Severity, 'ok'>;
export type ReviewStatus = 'unseen' | 'accepted' | 'dismissed';
export type View = 'documents' | 'project' | 'document' | 'rules' | 'history';
export type ProcessingPhase = 'uploaded' | 'queued' | 'processing' | 'ready' | 'failed' | 'unsupported';
export type TrafficLight = 'critical' | 'warning' | 'ok';
export type LawType = 'ALL' | '44-FZ' | '223-FZ';

export interface SeverityCounts { critical: number; warning: number; low: number; ok: number; unseen: number }
export interface CheckRule {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: RiskLevel;
  enabled: boolean;
  lawType?: LawType;
  semanticQuery?: string;
  llmPrompt?: string;
  legalReference?: string | null;
  sortOrder?: number;
  createdAt?: number;
  updatedAt?: number | null;
}
export type RuleDraft = Omit<CheckRule, 'id' | 'createdAt' | 'updatedAt'>;

export interface ProcessingState {
  phase: ProcessingPhase;
  label: string;
  progress: number;
  status: string;
  errorMessage: string | null;
}
export interface DocumentInfo extends ProcessingState {
  id: string;
  analysisId: string;
  name: string;
  relativePath: string | null;
  type: string | null;
  size: number | null;
  totalPages: number;
  isScanned: boolean;
  ocrPages: number;
  ocrConfidence: number | null;
  lawType: string | null;
  riskScore: number | null;
  trafficLight: TrafficLight | null;
  counts: SeverityCounts;
  rulesChecked: number;
  processingMs: number | null;
  hasPreview: boolean;
  createdAt: number;
  updatedAt: number | null;
}
export interface ProjectFile extends ProcessingState {
  /** Analysis identifier. Use a child document id to open a document. */
  id: string;
  name: string;
  type: string;
  size: number | null;
  addedAt: number;
  riskScore: number | null;
  trafficLight: TrafficLight | null;
  counts: SeverityCounts;
  rulesChecked: number;
  documents: DocumentInfo[];
}
export interface Project {
  id: string;
  title: string;
  description: string;
  files: ProjectFile[];
  createdAt: number;
  updatedAt: number;
  processingCount: number;
  counts: SeverityCounts;
  trafficLight: TrafficLight | null;
}
export type ProjectDraft = Pick<Project, 'title' | 'description'>;
export interface UploadResult { files: ProjectFile[]; errors: { name: string; detail: string }[] }

export interface Highlight { page: number; rects: number[][] }
export interface Finding {
  id: string;
  number: number | null;
  documentId: string;
  ruleId: string | null;
  title: string;
  description: string;
  severity: Severity;
  category: string;
  clause: string;
  page: number | null;
  quote: string;
  recommendation: string;
  comment: string;
  legalReference: string | null;
  highlights: Highlight[];
  quoteVerified: boolean;
  confidence: number | null;
  source: string;
  status: ReviewStatus;
  reviewerComment: string | null;
  reviewedAt: number | null;
  createdAt: number;
}
export interface Paragraph { clause: string; text: string; findingIds: string[] }
export interface Section { title: string; paragraphs: Paragraph[] }
export interface PageContent {
  page: number;
  totalPages: number;
  width: number;
  height: number;
  isOcr: boolean;
  ocrConfidence: number | null;
  sections: Section[];
}
export interface OutlineClause { clause: string; title: string; page: number }
export interface OutlineSection { title: string | null; page: number; clauses: OutlineClause[] }
export interface SearchHit { page: number; clause: string | null; snippet: string; highlights: Highlight[] }
export interface SearchResponse { query: string; total: number; hits: SearchHit[] }
export interface HistoryEntry {
  id: string;
  action: string;
  title: string;
  detail: string;
  /** ISO timestamp supplied by the server. */
  time: string;
  entityType: string;
  entityId: string | null;
}
export interface User {
  id: string;
  email: string;
  fullName: string;
  companyName: string | null;
  role: string;
  initials: string;
}
export type ReportFormat = 'docx' | 'pdf' | 'csv' | 'json';
export type ReportModeId = 'brief' | 'detailed' | 'protocol' | 'annotated';
export interface ReportMode { id: string; title: string; description: string; formats: string[] }
