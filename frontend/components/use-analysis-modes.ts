'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import type { AnalysisModes } from '@/lib/types';

/** Modes are loaded separately so an unavailable engine never hides project files. */
export function useAnalysisModes() {
  const [config, setConfig] = useState<AnalysisModes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.getAnalysisModes({ signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setConfig(value);
    }).catch(cause => {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision]);

  return { config, loading, error, refresh };
}
