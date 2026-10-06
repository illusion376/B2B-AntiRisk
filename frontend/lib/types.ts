export type Severity = 'critical' | 'warning' | 'low' | 'ok';
export type RiskLevel = Exclude<Severity, 'ok'>;
export type ReviewStatus = 'unseen' | 'accepted' | 'dismissed';
export type View = 'documents' | 'project' | 'document' | 'rules' | 'history';
export interface CheckRule {
  id: number;
  title: string;
  description: string;
  category: string;
  severity: RiskLevel;
  enabled: boolean;
}
export type RuleDraft = Omit<CheckRule, 'id'>;
export interface Project {
  id: string;
  title: string;
  description: string;
  files: ProjectFile[];
  updatedAt: number;
}
export interface ProjectFile {
  id: string;
  name: string;
  type: 'pdf' | 'txt' | 'zip';
  size: number;
  source: 'demo' | 'upload';
  addedAt: number;
}
export type ProjectDraft = Pick<Project, 'title' | 'description'>;
export interface Finding {
  id: number;
  title: string;
  description: string;
  severity: Severity;
  category: string;
  clause: string;
  page: number;
  quote: string;
  recommendation: string;
}
export interface Paragraph { clause: string; text: string; findingId?: number }
export interface Section { title: string; paragraphs: Paragraph[] }
export interface HistoryEntry { id: string; title: string; detail: string; time: string }
