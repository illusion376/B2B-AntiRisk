'use client';

import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

export function IconButton({ label, children, active, className = '', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return <button type="button" aria-label={label} title={label} className={`icon-button ${active ? 'is-active' : ''} ${className}`} {...props}>{children}</button>;
}

export function Modal({ title, children, onClose, wide = false, closeDisabled = false }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean; closeDisabled?: boolean }) {
  const titleId = useId();
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const close = () => { if (!dialog?.open) closeRef.current(); };
    dialog?.addEventListener('close', close);
    return () => { dialog?.removeEventListener('close', close); dialog?.close(); };
  }, []);
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} onCancel={e => { if (closeDisabled) e.preventDefault(); }} onClick={e => {
    if (closeDisabled || e.target !== e.currentTarget) return;
    const bounds = e.currentTarget.getBoundingClientRect();
    if (e.clientX < bounds.left || e.clientX > bounds.right || e.clientY < bounds.top || e.clientY > bounds.bottom) onClose();
  }} aria-labelledby={titleId}>
    <div className="modal-header"><h2 id={titleId}>{title}</h2><IconButton label="Закрыть окно" disabled={closeDisabled} onClick={onClose}><X size={20} /></IconButton></div>
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
