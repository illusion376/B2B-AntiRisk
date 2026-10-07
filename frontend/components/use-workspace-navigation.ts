'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { defaultRoute, normalizeRoute, parseRoute, serializeRoute, type WorkspaceRoute } from '@/lib/navigation';

export function useWorkspaceNavigation(totalPages: number) {
  const [route, setRoute] = useState<WorkspaceRoute>(defaultRoute);
  const current = useRef(route);

  useEffect(() => {
    const restore = () => {
      current.current = parseRoute(window.location.hash, totalPages);
      setRoute(current.current);
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
      window.history[replace ? 'replaceState' : 'pushState'](null, '', hash);
    }
    current.current = next;
    setRoute(next);
  }, [totalPages]);

  return { ...route, navigate };
}
