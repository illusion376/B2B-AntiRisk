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
type State = { page: number; activeFindings: Finding[]; statuses: Record<number, ReviewStatus>; navigatePage: (page: number) => void; selectFinding: (finding: Finding) => void; changeStatus: (id: number, status: ReviewStatus) => void };

export function useWorkspaceTools(state: State) {
  const latest = useRef(state);
  latest.current = state;
  useEffect(() => {
    const context = (document as ModelDocument).modelContext;
    if (!context?.registerTool) return;
    const controller = new AbortController();
    const tools: Tool[] = [
      {
        name: 'read_document_findings', description: 'Read the current page and enabled demonstration findings with review statuses. No real analysis is performed.',
        inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: {readOnlyHint: true, untrustedContentHint: true},
        execute: () => ({ page: latest.current.page, demo: true, findings: latest.current.activeFindings.map(f => ({id:f.id, title:f.title, severity:f.severity, page:f.page, status:latest.current.statuses[f.id] ?? 'unseen'})) }),
      },
      {
        name: 'navigate_to_finding', description: 'Open an enabled finding’s document page and highlight the relevant paragraph.',
        inputSchema: {type:'object',properties:{id:{type:'integer',minimum:1,maximum:20}},required:['id'],additionalProperties:false}, annotations:{readOnlyHint:false,untrustedContentHint:false},
        execute: input => { const id = (input as {id?:unknown} | null)?.id; const f = latest.current.activeFindings.find(f => f.id === id); if (!f) throw new Error('Finding not available'); flushSync(() => latest.current.selectFinding(f)); return {id:f.id,page:f.page}; },
      },
      {
        name: 'set_finding_review_status', description: 'Change a finding review status, save it in this browser, and add an entry to the current session history.',
        inputSchema:{type:'object',properties:{id:{type:'integer',minimum:1,maximum:20},status:{type:'string',enum:['unseen','accepted','dismissed']}},required:['id','status'],additionalProperties:false}, annotations:{readOnlyHint:false,untrustedContentHint:false},
        execute: input => { const value = input as {id?:unknown; status?:unknown} | null; const f = latest.current.activeFindings.find(f => f.id === value?.id); if (!f || !['unseen','accepted','dismissed'].includes(String(value?.status))) throw new Error('Invalid finding or status'); const status = value!.status as ReviewStatus; flushSync(() => latest.current.changeStatus(f.id, status)); return {id:f.id,status:latest.current.statuses[f.id] ?? 'unseen'}; },
      },
    ];
    for (const tool of tools) {
      try { void Promise.resolve(context.registerTool(tool, {signal:controller.signal})).catch(() => {}); } catch { /* Optional browser capability; the UI remains fully functional. */ }
    }
    return () => controller.abort();
  }, []);
}
