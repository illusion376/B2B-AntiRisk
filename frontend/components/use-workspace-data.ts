'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import type { CheckRule, DocumentInfo, Finding, HistoryEntry, OutlineSection, PageContent, Project, ReportMode, User } from '@/lib/types';

export function useWorkspaceData() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [rules, setRules] = useState<CheckRule[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [reportModes, setReportModes] = useState<ReportMode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const [nextProjects, nextRules, nextHistory, nextUser, nextModes] = await Promise.all([
          api.getProjects(options), api.getRules(options), api.getHistory(options), api.getUser(options), api.getReportModes(options),
        ]);
        if (controller.signal.aborted) return;
        setProjects(nextProjects); setRules(nextRules); setHistory(nextHistory); setUser(nextUser); setReportModes(nextModes); setError(null);
        const processing = nextProjects.some(project => project.processingCount > 0 || project.files.some(file => file.phase === 'queued' || file.phase === 'processing'));
        if (processing) timer = setTimeout(read, 2500);
      } catch (cause) { if (!controller.signal.aborted) setError(errorMessage(cause)); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void read();
    return () => { clearTimeout(timer); controller.abort(); };
  }, [revision]);
  return {projects, rules, history, user, reportModes, loading, error, refresh};
}

interface DocumentBundle { id: string; document: DocumentInfo; findings: Finding[]; outline: OutlineSection[] }
export function useLiveDocument(documentId: string | null, page: number) {
  const [bundle, setBundle] = useState<DocumentBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const refresh = useCallback(() => { generation.current += 1; setRevision(value => value + 1); }, []);
  const current = bundle?.id === documentId ? bundle : null;
  useEffect(() => {
    if (!documentId) return;
    const id = documentId;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setError(null);
    const ticket = generation.current;
    async function read() {
      try {
        const options = { signal: controller.signal };
        const document = await api.getDocument(id, options);
        const [findings, outline] = document.phase === 'ready'
          ? await Promise.all([api.getFindings(id, options), api.getOutline(id, options)]) : [[], []];
        if (controller.signal.aborted) return;
        if (ticket !== generation.current) return;
        setBundle({id, document, findings, outline}); setError(null);
        if (document.phase === 'queued' || document.phase === 'processing') timer = setTimeout(read, 2500);
      } catch (cause) {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      }
    }
    void read();
    return () => { clearTimeout(timer); controller.abort(); };
  }, [documentId, revision]);
  const [pageState, setPageState] = useState<{id:string; page:number; content:PageContent | null; error:string | null; loading:boolean} | null>(null);
  const [pageRevision, setPageRevision] = useState(0);
  const ready = current?.document.phase === 'ready';
  useEffect(() => {
    if (!documentId || !ready) return;
    const id = documentId;
    const controller = new AbortController();
    setPageState({id, page, content:null, error:null, loading:true});
    api.getPage(id, page, {signal:controller.signal}).then(content => {
      if (!controller.signal.aborted) setPageState({id, page, content, error:null, loading:false});
    }).catch(cause => {
      if (!controller.signal.aborted) setPageState({id, page, content:null, error:errorMessage(cause), loading:false});
    });
    return () => controller.abort();
  }, [documentId, page, ready, pageRevision, revision]);
  const currentPage = pageState?.id === documentId && pageState.page === page ? pageState : null;
  const replaceFinding = useCallback((finding: Finding) => setBundle(previous => previous?.id === finding.documentId ? {...previous, findings:previous.findings.map(item => item.id === finding.id ? finding : item)} : previous), []);
  return {document:current?.document ?? null, findings:current?.findings ?? [], outline:current?.outline ?? [], error,
    pageContent:currentPage?.content ?? null, pageError:currentPage?.error ?? null, pageLoading:ready && (!currentPage || currentPage.loading),
    retryPage:() => setPageRevision(value => value + 1), refresh, replaceFinding};
}
