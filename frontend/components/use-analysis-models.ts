'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import { analysisModelPreferenceKey, savedAnalysisModel } from '@/lib/analysis-models';
import type { AnalysisModels } from '@/lib/types';

export function useAnalysisModels() {
  const [catalog, setCatalog] = useState<AnalysisModels | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preference, setPreference] = useState<string | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);

  useEffect(() => {
    try { setPreference(savedAnalysisModel(window.localStorage.getItem(analysisModelPreferenceKey))); }
    catch { setStorageError(true); }
    setStorageReady(true);
    const sync = (event: StorageEvent) => {
      if (event.key === analysisModelPreferenceKey || event.key === null) setPreference(savedAnalysisModel(event.newValue));
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.getAnalysisModels({ signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setCatalog(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorMessage(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [version]);

  const selectedModel = preference ?? catalog?.defaultModel ?? null;
  function selectModel(id: string) {
    if (loading || error || !catalog?.models.some(model => model.id === id && model.available)) return;
    setPreference(id);
    try { window.localStorage.setItem(analysisModelPreferenceKey, id); setStorageError(false); }
    catch { setStorageError(true); }
  }

  return { catalog, loading, error, refresh, selectedModel, selectModel, storageError,
    ready: storageReady && !loading && !error && catalog?.models.some(model => model.id === selectedModel && model.available) === true };
}

export type AnalysisModelsState = ReturnType<typeof useAnalysisModels>;
