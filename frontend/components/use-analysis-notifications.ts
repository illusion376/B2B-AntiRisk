'use client';

import { useEffect, useRef, useState } from 'react';
import { analysisEvents, analysisSnapshot } from '@/lib/analysis-notifications';
import type { AnalysisNotice, AnalysisSnapshot } from '@/lib/analysis-notifications';
import type { Project } from '@/lib/types';
import type { WorkspacePreferences } from '@/lib/workspace-preferences';

type DesktopPermission = NotificationPermission | 'unsupported';
const browserPermission = (): DesktopPermission =>
  window.isSecureContext && 'Notification' in window ? Notification.permission : 'unsupported';

export function useAnalysisNotifications(projects: Project[], ready: boolean, preferences: WorkspacePreferences,
  onPreferences: (patch: Partial<WorkspacePreferences>) => void) {
  const [notices, setNotices] = useState<AnalysisNotice[]>([]);
  const [permission, setPermission] = useState<DesktopPermission>('unsupported');
  const [requesting, setRequesting] = useState(false);
  const previous = useRef<AnalysisSnapshot | null>(null);
  const permissionLock = useRef(false);
  useEffect(() => {
    const sync = () => setPermission(browserPermission());
    sync();
    window.addEventListener('focus', sync);
    return () => window.removeEventListener('focus', sync);
  }, []);
  useEffect(() => {
    if (!ready) return;
    const current = analysisSnapshot(projects);
    const fresh = previous.current ? analysisEvents(previous.current, current)
      .filter(notice => preferences.notifications[notice.kind]) : [];
    previous.current = current;
    if (!fresh.length) return;
    setNotices(items => [...fresh.reverse(), ...items].slice(0, 30));
    if (preferences.notifications.desktop && browserPermission() === 'granted') {
      for (const notice of fresh) {
        try { new Notification(notice.title, { body: notice.body, icon: '/favicon.svg', tag: notice.id }); }
        catch { /* Уведомление остаётся доступным на сайте, включая мобильные браузеры. */ }
      }
    }
  }, [projects, ready, preferences.notifications]);

  async function toggleDesktop() {
    if (permissionLock.current) return;
    if (preferences.notifications.desktop && browserPermission() === 'granted') {
      onPreferences({ notifications: { ...preferences.notifications, desktop: false } });
      return;
    }
    if (browserPermission() === 'unsupported' || browserPermission() === 'denied') return;
    permissionLock.current = true;
    setRequesting(true);
    try {
      const granted = await Notification.requestPermission();
      setPermission(granted);
      onPreferences({ notifications: { ...preferences.notifications, desktop: granted === 'granted' } });
    } catch { setPermission(browserPermission()); }
    finally { permissionLock.current = false; setRequesting(false); }
  }

  return { notices, permission, requesting, toggleDesktop,
    unread: notices.filter(notice => !notice.read).length,
    markRead: (id: string) => setNotices(items => items.map(item => item.id === id ? { ...item, read: true } : item)),
    markAllRead: () => setNotices(items => items.map(item => ({ ...item, read: true }))),
  };
}
