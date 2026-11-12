export type Severity = 'critical' | 'warning' | 'low' | 'ok' | 'unknown';
export type RiskLevel = Exclude<Severity, 'ok' | 'unknown'>;
export type ReviewStatus = 'unseen' | 'accepted' | 'dismissed';
export type View = 'documents' | 'project' | 'document' | 'rules' | 'settings';
export type ProcessingPhase = 'uploaded' | 'queued' | 'processing' | 'ready' | 'failed' | 'unsupported';
export type TrafficLight = 'critical' | 'warning' | 'ok' | 'unknown';
export type LawType = 'ALL' | '44-FZ' | '223-FZ';
export type AnalysisMode = 'llm' | 'nli' | 'keyword';
export type AnalysisSensitivity = 'strict' | 'balanced' | 'sensitive';

export interface AnalysisModeOption {
  id: AnalysisMode;
  label: string;
  available: boolean;
  description: string;
}
export interface AnalysisModes {
  defaultMode: AnalysisMode;
  modes: AnalysisModeOption[];
  configuredModel: string | null;
}

export interface AnalysisModel {
  id: string;
  label: string;
  provider: string;
  providerId: string;
  description: string;
  available: boolean;
  recommended: boolean;
}
export interface AnalysisModels {
  defaultModel: string | null;
  models: AnalysisModel[];
  source: 'provider' | 'fallback';
  warning: string | null;
}

export interface SeverityCounts { critical: number; warning: number; low: number; ok: number; unknown: number; unseen: number }
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

export interface RuleTestFinding {
  id: string;
  severity: Severity;
  title: string;
  shortDescription: string | null;
  page: number | null;
  clause: string | null;
  quote: string | null;
  comment: string | null;
  counterProposal: string | null;
  confidence: number | null;
  quoteVerified: boolean;
}

export interface RuleTestFragment {
  page: number;
  clauseTitle: string | null;
  content: string;
  score: number;
}

export interface RuleTestResult {
  ruleId: string;
  documentId: string | null;
  documentName: string | null;
  verdict: string;
  findings: RuleTestFinding[];
  fragments: RuleTestFragment[];
  guidance: string[];
  executionMs: number | null;
}

export interface RuleTestRequest {
  documentId?: string;
  customText?: string;
}

export interface ProcessingState {
  phase: ProcessingPhase;
  label: string;
  progress: number;
  status: string;
  errorMessage: string | null;
}
export type QualityStatus = 'ok' | 'low' | 'unknown' | 'native';
export type QualitySlaStatus = 'within' | 'exceeded' | 'not_configured' | 'not_measured' | 'not_applicable';
export interface ReviewPageQuality {
  page: number;
  status: 'low' | 'unknown';
  confidence: number | null;
  reason: string;
  warning: string;
}
export interface PageQuality {
  status: QualityStatus;
  confidence: number | null;
  confidenceThreshold: number | null;
  manualReviewRequired: boolean;
  warning: string | null;
  reason: string | null;
}
export interface DocumentQuality {
  status: QualityStatus;
  confidenceThreshold: number | null;
  confidence: number | null;
  totalPages: number;
  ocrPages: number;
  nativePages: number;
  ocrPercent: number | null;
  nativePercent: number | null;
  measuredOcrPages: number;
  reviewPages: ReviewPageQuality[];
  manualReviewRequired: boolean;
  warning: string | null;
  processingMs: number | null;
  processingKind: 'full' | 'reanalysis' | null;
  slaMs: number | null;
  slaStatus: QualitySlaStatus;
}
export interface DocumentInfo extends ProcessingState {
  id: string;
  analysisId: string;
  analysisMode: AnalysisMode | null;
  analysisSensitivity: AnalysisSensitivity | null;
  llmModel?: string | null;
  chatRevision?: string | null;
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
  quality?: DocumentQuality | null;
  hasPreview: boolean;
  createdAt: number;
  updatedAt: number | null;
}
export interface ProjectFile extends ProcessingState {

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
  isRuleTest: boolean;
  files: ProjectFile[];
  createdAt: number;
  updatedAt: number;
  processingCount: number;
  counts: SeverityCounts;
  trafficLight: TrafficLight | null;
}
export type ProjectDraft = Pick<Project, 'title' | 'description'>;
export interface UploadResult { files: ProjectFile[]; errors: { name: string; detail: string }[] }
export interface RuleTestUploadResult { projectId: string; documents: DocumentInfo[] }

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
  quality?: PageQuality | null;
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

  time: string;
  entityType: string;
  entityId: string | null;
}
export interface QualitySettings {
  ocrMinConfidence: number;
  processingSlaSeconds: number | null;
}
export interface User {
  id: string;
  email: string;
  fullName: string;
  companyName: string | null;
  role: string;
  initials: string;
  qualitySettings: QualitySettings | null;
}
export interface UserProfileDraft { fullName: string; companyName: string }
export type ReportFormat = 'docx' | 'pdf' | 'csv' | 'json';
export type ReportModeId = 'brief' | 'detailed' | 'protocol' | 'annotated';
export interface ReportMode { id: string; title: string; description: string; formats: string[] }

export type ChatMode = 'question' | 'report' | 'protocol';
export interface ChatSource { id: string; label: string; page: number | null; findingId: string | null; quote: string }
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  findingId: string | null;
  sources: ChatSource[];
  draftTitle: string | null;
  draftContent: string | null;
  createdAt: number;
}
export interface ChatHistory { available: boolean; unavailableReason: string | null; messages: ChatMessage[] }
