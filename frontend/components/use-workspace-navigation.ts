'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { DEFAULT_ROUTE, formatRoute, normalizeRoute, parseRoute, type WorkspaceRoute } from '@/lib/routes';

/**
 * Состояние навигации в location.hash: Back/Forward и перезагрузка сохраняют раздел,
 * проект, страницу и выбранное замечание.
 */
export function useWorkspaceNavigation(totalPages: number) {
  const [route, setRoute] = useState<WorkspaceRoute>(DEFAULT_ROUTE);
  const current = useRef(route);

  useEffect(() => {
    const sync = () => {
      const next = parseRoute(window.location.hash, totalPages, current.current);
      current.current = next;
      setRoute(next);
    };
    sync();
    // pushState не вызывает hashchange, а «Назад» по таким записям вызывает popstate
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, [totalPages]);

  const navigate = useCallback((patch: Partial<WorkspaceRoute>, replace = false) => {
    const next = normalizeRoute({ ...current.current, ...patch }, totalPages);
    current.current = next;
    setRoute(next);
    const hash = formatRoute(next);
    if (window.location.hash === hash) return;
    if (replace) window.history.replaceState(window.history.state, '', hash);
    else window.history.pushState(null, '', hash);
  }, [totalPages]);

  return { ...route, navigate };
}
