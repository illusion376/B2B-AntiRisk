/** HTTP payloads from backend/app/schemas.py. Keep snake_case at this boundary. */
import type { AnalysisMode, AnalysisModeOption, AnalysisSensitivity, Highlight, LawType, ProcessingPhase, ReportMode, ReviewStatus, RiskLevel, Severity, SeverityCounts, TrafficLight } from './types';

export interface AnalysisModesDto {
  default_mode: AnalysisMode;
  modes: AnalysisModeOption[];
  configured_model?: string | null;
}

export interface DocumentDto {
  id: string; analysis_id: string; file_name: string; relative_path: string | null;
  analysis_mode: AnalysisMode | null;
  analysis_sensitivity?: AnalysisSensitivity | null;
  file_type: string | null; file_size: number | null; status: string; phase: ProcessingPhase;
  label: string; progress: number; total_pages: number; is_scanned: boolean; ocr_pages: number;
  ocr_confidence: number | null; law_type: string | null; risk_score: number | null;
  traffic_light: TrafficLight | null; counts: SeverityCounts; rules_checked: number;
  error_message: string | null; processing_ms: number | null; has_preview: boolean;
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
  sections: { title: string; paragraphs: { clause: string; text: string; finding_ids: string[] }[] }[];
}
export interface UserDto {
  id: string; email: string; full_name: string; company_name: string | null; role: string; initials: string;
}
export interface HistoryDto {
  id: string; action: string; title: string; detail: string; time: string; entity_type: string; entity_id: string | null;
}
export interface UploadDto { files: ProjectFileDto[]; errors: { name: string; detail: string }[] }
export type ReportModeDto = ReportMode;
