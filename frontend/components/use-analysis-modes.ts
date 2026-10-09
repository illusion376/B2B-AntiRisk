'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import type { AnalysisMode, AnalysisModes } from '@/lib/types';

const preferenceKey = 'b2b-antirisk.analysis-mode';
const savedMode = (value: string | null): AnalysisMode | null =>
  value === 'llm' || value === 'keyword' || value === 'nli' ? value : null;

export function useAnalysisModes() {
  const [config, setConfig] = useState<AnalysisModes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preference, setPreference] = useState<AnalysisMode | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);

  useEffect(() => {
    try { setPreference(savedMode(window.localStorage.getItem(preferenceKey))); }
    catch { setStorageError(true); }
    const syncPreference = (event: StorageEvent) => {
      if (event.key === preferenceKey || event.key === null) setPreference(savedMode(event.newValue));
    };
    window.addEventListener('storage', syncPreference);
    return () => window.removeEventListener('storage', syncPreference);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.getAnalysisModes({ signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setConfig(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorMessage(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [version]);

  function selectMode(mode: AnalysisMode) {
    if (loading || error || !config?.modes.some(option => option.id === mode && option.available)) return;
    setPreference(mode);
    try {
      window.localStorage.setItem(preferenceKey, mode);
      setStorageError(false);
    } catch { setStorageError(true); }
  }

  // Сохранённый, но теперь недоступный режим требует явного нового выбора.
  return { config, loading, error, refresh, selectMode, storageError,
    selectedMode: preference ?? config?.defaultMode ?? null };
}
