'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { defaultRoute, normalizeRoute, parseRoute, serializeRoute, type WorkspaceRoute } from '@/lib/navigation';

export function useWorkspaceNavigation(totalPages?: number) {
  const [route, setRoute] = useState<WorkspaceRoute>({ ...defaultRoute });
  const current = useRef(route);

  useEffect(() => {
    const restore = () => {
      const next = parseRoute(window.location.hash, totalPages);
      const hash = serializeRoute(next);
      if (window.location.hash !== hash) window.history.replaceState(window.history.state, '', hash);
      current.current = next;
      setRoute(next);
    };
    restore();
    window.addEventListener('hashchange', restore);
    window.addEventListener('popstate', restore);
    return () => {
      window.removeEventListener('hashchange', restore);
      window.removeEventListener('popstate', restore);
    };
  }, [totalPages]);

  const navigate = useCallback((patch: Partial<WorkspaceRoute>, replace = false) => {
    const next = normalizeRoute({ ...current.current, ...patch }, totalPages);
    const hash = serializeRoute(next);
    if (window.location.hash !== hash) {
      window.history[replace ? 'replaceState' : 'pushState'](window.history.state, '', hash);
    }
    current.current = next;
    setRoute(next);
  }, [totalPages]);

  return { ...route, navigate };
}
