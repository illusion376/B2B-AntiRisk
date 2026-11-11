import type { AnalysisMode, AnalysisModeOption, AnalysisSensitivity, Highlight, LawType, ProcessingPhase, QualitySlaStatus, QualityStatus, ReportMode, ReviewStatus, RiskLevel, Severity, SeverityCounts, TrafficLight } from './types';

export interface AnalysisModesDto {
  default_mode: AnalysisMode;
  modes: AnalysisModeOption[];
  configured_model?: string | null;
}

export interface AnalysisModelsDto {
  default_model: string | null;
  models: { id: string; label: string; provider: string; provider_id: string; description: string; available: boolean; recommended: boolean }[];
  source: 'provider' | 'fallback';
  warning?: string | null;
}

export interface PageQualityDto {
  status: QualityStatus; confidence: number | null; confidence_threshold: number | null;
  manual_review_required: boolean; warning: string | null; reason: string | null;
}
export interface DocumentQualityDto {
  status: QualityStatus; confidence_threshold: number | null; confidence: number | null;
  total_pages: number; ocr_pages: number; native_pages: number;
  ocr_percent: number | null; native_percent: number | null; measured_ocr_pages: number;
  review_pages: { page: number; status: 'low' | 'unknown'; confidence: number | null; reason: string; warning: string }[];
  manual_review_required: boolean; warning: string | null;
  processing_ms: number | null; processing_kind: 'full' | 'reanalysis' | null;
  sla_ms: number | null; sla_status: QualitySlaStatus;
}

export interface DocumentDto {
  id: string; analysis_id: string; file_name: string; relative_path: string | null;
  analysis_mode: AnalysisMode | null;
  llm_model?: string | null;
  analysis_sensitivity?: AnalysisSensitivity | null;
  chat_revision?: string | null;
  file_type: string | null; file_size: number | null; status: string; phase: ProcessingPhase;
  label: string; progress: number; total_pages: number; is_scanned: boolean; ocr_pages: number;
  ocr_confidence: number | null; law_type: string | null; risk_score: number | null;
  traffic_light: TrafficLight | null; counts: SeverityCounts; rules_checked: number;
  error_message: string | null; processing_ms: number | null; has_preview: boolean;
  quality?: DocumentQualityDto | null;
  created_at: string; updated_at: string | null;
}
export interface ProjectFileDto {
  id: string; name: string; type: string; size: number | null; added_at: string;
  phase: ProcessingPhase; label: string; progress: number; status: string;
  error_message: string | null; risk_score: number | null; traffic_light: TrafficLight | null;
  counts: SeverityCounts; rules_checked: number; documents: DocumentDto[];
}
export interface ProjectDto {
  id: string; title: string; description: string; created_at: string; updated_at: string;
  files: ProjectFileDto[]; processing_count: number; counts: SeverityCounts; traffic_light: TrafficLight | null;
}
export interface FindingDto {
  id: string; number: number | null; document_id: string; rule_id: string | null;
  title: string; description: string; severity: Severity; category: string; clause: string;
  page: number | null; quote: string; recommendation: string; comment: string;
  legal_reference: string | null; highlights: Highlight[]; quote_verified: boolean;
  confidence: number | null; source: string; status: ReviewStatus; reviewer_comment: string | null;
  reviewed_at: string | null; created_at: string;
}
export interface FindingsDto {
  document_id: string | null; total: number;
  groups: { severity: Severity; label: string; count: number; items: FindingDto[] }[];
  categories: string[]; statuses: Record<string, number>;
}
export interface RuleDto {
  id: string; title: string; description: string; category: string; severity: RiskLevel; enabled: boolean;
  law_type: LawType; semantic_query: string; llm_prompt: string; legal_reference: string | null;
  sort_order: number; created_at: string; updated_at: string | null;
}
export interface PageDto {
  page: number; total_pages: number; width: number; height: number;
  is_ocr: boolean; ocr_confidence: number | null;
  quality?: PageQualityDto | null;
  sections: { title: string; paragraphs: { clause: string; text: string; finding_ids: string[] }[] }[];
}
export interface QualitySettingsDto {
  ocr_min_confidence: number;
  processing_sla_seconds: number | null;
}
export interface UserDto {
  id: string; email: string; full_name: string; company_name: string | null; role: string; initials: string;
  quality_settings?: QualitySettingsDto | null;
}
export interface HistoryDto {
  id: string; action: string; title: string; detail: string; time: string; entity_type: string; entity_id: string | null;
}
export interface UploadDto { files: ProjectFileDto[]; errors: { name: string; detail: string }[] }
export type ReportModeDto = ReportMode;
export interface ChatMessageDto {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  finding_id: string | null;
  sources: { id: string; label: string; page: number | null; finding_id: string | null; quote: string }[];
  draft_title: string | null;
  draft_content: string | null;
  created_at: string;
}
export interface ChatHistoryDto { available: boolean; unavailable_reason: string | null; messages: ChatMessageDto[] }
