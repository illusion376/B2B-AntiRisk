'use client';

import { useCallback, useEffect, useState } from 'react';
import { emptyOnboarding, onboardingKey, parseOnboarding, projectTourStep, workspaceTour } from '@/lib/onboarding';
import type { OnboardingProgress } from '@/lib/onboarding';
import type { Project, View } from '@/lib/types';

export function useOnboarding(userId: string | null, ready: boolean, view: View, projectId: string, project?: Project) {
  const key = userId ? onboardingKey(userId) : null;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [progress, setProgress] = useState<OnboardingProgress>(emptyOnboarding);
  const [workspaceStep, setWorkspaceStep] = useState<number | null>(null);

  useEffect(() => {
    setWorkspaceStep(null);
    if (!key) { setLoadedKey(null); return; }
    let saved = { ...emptyOnboarding };
    try { saved = parseOnboarding(window.localStorage.getItem(key)); } catch { /* Keep the guide usable without storage. */ }
    setProgress(saved);
    setLoadedKey(key);
    const sync = (event: StorageEvent) => {
      if (event.key !== key && event.key !== null) return;
      const next = parseOnboarding(event.key === null ? null : event.newValue);
      setProgress(next);
      if (next.workspaceDone) setWorkspaceStep(null);
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [key]);

  useEffect(() => {
    if (!key || loadedKey !== key) return;
    try { window.localStorage.setItem(key, JSON.stringify(progress)); } catch { /* Progress lasts for this visit. */ }
  }, [key, loadedKey, progress]);

  useEffect(() => {
    if (ready && key && loadedKey === key && !progress.workspaceDone && !progress.projectId && view === 'documents') {
      setWorkspaceStep(previous => previous ?? 0);
    }
  }, [ready, key, loadedKey, progress.workspaceDone, progress.projectId, view]);

  useEffect(() => {
    if (ready && loadedKey === key && view === 'document' && progress.projectId === projectId) {
      setProgress(previous => ({ ...previous, projectDone: true, projectId: null }));
    }
  }, [ready, key, loadedKey, view, projectId, progress.projectId]);

  const next = useCallback(() => {
    if (workspaceStep === null) return;
    if (workspaceStep + 1 < workspaceTour.length) setWorkspaceStep(workspaceStep + 1);
    else {
      setWorkspaceStep(null);
      setProgress(previous => ({ ...previous, workspaceDone: true }));
    }
  }, [workspaceStep]);

  const close = useCallback(() => {
    if (workspaceStep !== null) {
      setWorkspaceStep(null);
      setProgress(previous => ({ ...previous, workspaceDone: true }));
    } else setProgress(previous => ({ ...previous, projectDone: true, projectId: null }));
  }, [workspaceStep]);

  const projectCreated = useCallback((id: string) => {
    setWorkspaceStep(null);
    setProgress(previous => ({ ...previous, workspaceDone: true, projectId: previous.projectDone ? null : id }));
  }, []);

  const projectDeleted = useCallback((id: string) => {
    setProgress(previous => previous.projectId === id ? { ...previous, projectId: null } : previous);
  }, []);

  const restart = useCallback((id?: string) => {
    if (id) {
      setWorkspaceStep(null);
      setProgress(previous => ({ ...previous, workspaceDone: true, projectDone: false, projectId: id }));
    } else {
      setProgress(previous => ({ ...previous, workspaceDone: false }));
      setWorkspaceStep(0);
    }
  }, []);

  const workspaceActive = workspaceStep !== null;
  const step = !ready || !key || loadedKey !== key ? null : workspaceActive ? workspaceTour[workspaceStep]
    : !progress.projectDone && progress.projectId === projectId && view === 'project' && project ? projectTourStep(project) : null;
  return { step, workspaceActive, workspaceStep, next, close, projectCreated, projectDeleted, restart,
    previous: workspaceStep !== null && workspaceStep > 0 ? () => setWorkspaceStep(workspaceStep - 1) : undefined };
}
