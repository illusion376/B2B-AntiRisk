'use client';

import { useCallback, useEffect, useState } from 'react';
import { defaultPreferences, normalizePreferences, parsePreferences, preferenceKey } from '@/lib/workspace-preferences';
import type { WorkspacePreferences } from '@/lib/workspace-preferences';

export function useWorkspacePreferences() {
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [ready, setReady] = useState(false);
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    try { setPreferences(parsePreferences(window.localStorage.getItem(preferenceKey))); }
    catch { setStorageError(true); }
    setReady(true);
    const sync = (event: StorageEvent) => {
      if (event.key === preferenceKey || event.key === null) setPreferences(parsePreferences(event.newValue));
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  useEffect(() => {
    if (!ready) return;
    try { window.localStorage.setItem(preferenceKey, JSON.stringify(preferences)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [preferences, ready]);
  const update = useCallback((patch: Partial<WorkspacePreferences>) => {
    setPreferences(previous => normalizePreferences({ ...previous, ...patch }));
  }, []);
  return { preferences, ready, storageError, update };
}
