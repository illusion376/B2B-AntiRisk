'use client';

import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

export function IconButton({ label, children, active, className = '', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return <button type="button" aria-label={label} title={label} className={`icon-button ${active ? 'is-active' : ''} ${className}`} {...props}>{children}</button>;
}

export function Modal({ title, children, onClose, wide = false }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const close = () => closeRef.current();
    dialog?.addEventListener('close', close);
    return () => { dialog?.removeEventListener('close', close); dialog?.close(); };
  }, []);
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} onClick={e => { if (e.target === e.currentTarget) onClose(); }} aria-labelledby="modal-title">
    <div className="modal-header"><h2 id="modal-title">{title}</h2><IconButton label="Закрыть окно" onClick={onClose}><X size={20} /></IconButton></div>
    {children}
  </dialog>;
}

export function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const lower = text.toLocaleLowerCase('ru');
  const match = needle.toLocaleLowerCase('ru');
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let index = lower.indexOf(match);
  while (index !== -1) {
    parts.push(text.slice(cursor, index), <mark className="search-mark" key={index}>{text.slice(index, index + needle.length)}</mark>);
    cursor = index + needle.length;
    index = lower.indexOf(match, cursor);
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}
