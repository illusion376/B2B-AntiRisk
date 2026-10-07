'use client';

import { useEffect, useRef } from 'react';
import { flushSync } from 'react-dom';
import type { Finding, ReviewStatus } from '@/lib/types';

interface Tool {
  name: string;
  description: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute: (input: unknown) => unknown;
}
interface ModelDocument extends Document { modelContext?: { registerTool: (tool: Tool, options?: { signal?: AbortSignal }) => void | Promise<void> } }
type State = {
  documentId?: string | null;
  page: number;
  activeFindings: Finding[];
  statuses: Record<string, ReviewStatus>;
  navigatePage?: (page: number) => void;
  selectFinding: (finding: Finding) => void;
  changeStatus: (id: string, status: ReviewStatus) => Promise<void>;
};

export function useWorkspaceTools(state: State) {
  const latest = useRef(state);
  latest.current = state;
  useEffect(() => {
    const context = (document as ModelDocument).modelContext;
    if (!context?.registerTool) return;
    const controller = new AbortController();
    const tools: Tool[] = [
      {
        name: 'read_document_findings', description: 'Read findings returned by the backend for the current document, with their review statuses.',
        inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: {readOnlyHint: true, untrustedContentHint: true},
        execute: () => ({ documentId: latest.current.documentId ?? null, page: latest.current.page, findings: latest.current.activeFindings.map(f => ({id:f.id, number:f.number, title:f.title, severity:f.severity, page:f.page, source:f.source, quoteVerified:f.quoteVerified, status:latest.current.statuses[f.id] ?? f.status})) }),
      },
      {
        name: 'navigate_to_finding', description: 'Select a finding in the current document and open its page when a page is available.',
        inputSchema: {type:'object',properties:{id:{type:'string',minLength:1}},required:['id'],additionalProperties:false}, annotations:{readOnlyHint:false,untrustedContentHint:false},
        execute: input => {
          const id = (input as {id?:unknown} | null)?.id;
          const finding = latest.current.activeFindings.find(f => f.id === id);
          if (!finding) throw new Error('Finding not available in the current document');
          flushSync(() => latest.current.selectFinding(finding));
          return {id:finding.id,documentId:finding.documentId,page:finding.page};
        },
      },
      {
        name: 'set_finding_review_status', description: 'Persist a finding review status through the backend API and return only after the save succeeds.',
        inputSchema:{type:'object',properties:{id:{type:'string',minLength:1},status:{type:'string',enum:['unseen','accepted','dismissed']}},required:['id','status'],additionalProperties:false}, annotations:{readOnlyHint:false,untrustedContentHint:false},
        execute: async input => {
          const value = input as {id?:unknown; status?:unknown} | null;
          const finding = latest.current.activeFindings.find(f => f.id === value?.id);
          if (!finding || !['unseen','accepted','dismissed'].includes(String(value?.status))) throw new Error('Invalid finding or status');
          const status = value!.status as ReviewStatus;
          await latest.current.changeStatus(finding.id, status);
          return {id:finding.id,documentId:finding.documentId,status};
        },
      },
    ];
    for (const tool of tools) {
      try { void Promise.resolve(context.registerTool(tool, {signal:controller.signal})).catch(() => {}); } catch { /* Optional browser capability; the UI remains fully functional. */ }
    }
    return () => controller.abort();
  }, []);
}
