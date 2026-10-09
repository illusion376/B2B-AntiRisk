'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Bell, CheckCheck, CircleCheck, ShieldAlert } from 'lucide-react';
import type { AnalysisNotice } from '@/lib/analysis-notifications';
import './notifications.css';

interface Props {
  notices: AnalysisNotice[];
  unread: number;
  onRead: (id: string) => void;
  onReadAll: () => void;
  onOpen: (notice: AnalysisNotice) => void;
}

export function NotificationCenter({ notices, unread, onRead, onReadAll, onOpen }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    window.addEventListener('pointerdown', outside);
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('pointerdown', outside); window.removeEventListener('keydown', escape); };
  }, [open]);
  return <div className="notification-center" ref={root}>
    <button ref={trigger} type="button" className="icon-button notification-trigger" aria-label={unread ? `Уведомления: ${unread} новых` : 'Уведомления'} title="Уведомления" aria-expanded={open} aria-controls={open ? 'analysis-notices' : undefined} onClick={() => setOpen(value => !value)}>
      <Bell size={18} />{unread > 0 && <span className="notification-badge" aria-hidden="true">{Math.min(unread, 99)}</span>}
    </button>
    {open && <section className="notification-popover" id="analysis-notices" aria-label="Уведомления анализа">
      <div className="notification-heading"><h2>Уведомления</h2>{unread > 0 && <button type="button" onClick={onReadAll} title="Отметить все прочитанными" aria-label="Отметить все прочитанными"><CheckCheck size={17} /></button>}</div>
      {notices.length ? <ul>{notices.map(notice => {
        const Icon = notice.kind === 'critical' ? ShieldAlert : notice.kind === 'error' ? AlertCircle : CircleCheck;
        return <li key={notice.id}><button type="button" className={`notification-item ${notice.kind}${notice.read ? '' : ' unread'}`} onClick={() => { onRead(notice.id); onOpen(notice); setOpen(false); }}>
          <span className="notification-kind-icon"><Icon size={17} /></span><span><strong>{notice.title}</strong><span>{notice.body}</span><time dateTime={new Date(notice.createdAt).toISOString()}>{new Date(notice.createdAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</time></span>
          {!notice.read && <i aria-label="Не прочитано" />}
        </button></li>;
      })}</ul> : <p className="notification-empty">Здесь появятся сообщения о новых результатах проверки.</p>}
    </section>}
    <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">{unread > 0 ? `Новых уведомлений: ${unread}. ${notices[0]?.title ?? ''}` : ''}</span>
  </div>;
}
