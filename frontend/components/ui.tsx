'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, X } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
}

export function CustomSelect({
  value,
  onChange,
  options,
  className = '',
  disabled = false,
  ariaLabel,
  id,
  ariaDescribedBy,
  icon,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
  disabled?: boolean;
  ariaLabel?: string;
  id?: string;
  ariaDescribedBy?: string;
  icon?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const selectId = useId();
  const triggerId = id || `${selectId}-trigger`;
  const menuId = `${selectId}-listbox`;
  const selectedIndex = options.findIndex(option => option.value === value);
  const highlightedIndex = Math.min(activeIndex, options.length - 1);
  const currentOption = options.find(o => o.value === value) || options[0];

  function openMenu(index = Math.max(0, selectedIndex)) {
    if (disabled || !options.length) return;
    setActiveIndex(index);
    setOpen(true);
  }

  function closeMenu() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function selectOption(index: number) {
    const option = options[index];
    if (!option || disabled) return;
    onChange(option.value);
    closeMenu();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement | HTMLUListElement>) {
    if (disabled || !options.length) return;
    if (event.key === 'Tab') {
      if (open) closeMenu();
      return;
    }
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        closeMenu();
      }
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) openMenu(selectedIndex < 0 && event.key === 'ArrowUp' ? options.length - 1 : Math.max(0, selectedIndex));
      else setActiveIndex(Math.max(0, Math.min(options.length - 1, highlightedIndex + (event.key === 'ArrowDown' ? 1 : -1))));
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      openMenu(event.key === 'Home' ? 0 : options.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (open) selectOption(highlightedIndex);
      else openMenu();
    }
  }

  useEffect(() => {
    if (!open) return;
    menuRef.current?.focus({ preventScroll: true });
    function handlePointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [open]);

  useEffect(() => {
    if (open) menuRef.current?.children[highlightedIndex]?.scrollIntoView({ block: 'nearest' });
  }, [open, highlightedIndex]);

  return (
    <div ref={containerRef} className={`custom-select-wrap ${className} ${open ? 'is-open' : ''}`}>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        className="custom-select-trigger"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onKeyDown={handleKeyDown}
        onClick={() => open ? closeMenu() : openMenu()}
      >
        {icon && <span className="custom-select-icon">{icon}</span>}
        <span className="custom-select-label">{currentOption?.label ?? value}</span>
        <ChevronDown size={14} className={`custom-select-arrow ${open ? 'is-open' : ''}`} />
      </button>
      {open && (
        <ul ref={menuRef} id={menuId} className="custom-select-menu" role="listbox" tabIndex={-1} aria-label={ariaLabel} aria-labelledby={ariaLabel ? undefined : triggerId} aria-activedescendant={`${menuId}-option-${highlightedIndex}`} onKeyDown={handleKeyDown}>
          {options.map((option, index) => {
            const isSelected = option.value === value;
            return (
              <li
                key={option.value}
                id={`${menuId}-option-${index}`}
                role="option"
                aria-selected={isSelected}
                className={`custom-select-item opt-${option.value} ${isSelected ? 'is-selected' : ''} ${index === highlightedIndex ? 'is-highlighted' : ''}`}
                onPointerMove={() => setActiveIndex(index)}
                onClick={() => selectOption(index)}
              >
                <span>{option.label}</span>
                {isSelected && <Check size={14} className="custom-select-check" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function IconButton({ label, children, active, className = '', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return <button type="button" aria-label={label} title={label} className={`icon-button ${active ? 'is-active' : ''} ${className}`} {...props}>{children}</button>;
}

export function Modal({ title, children, onClose, wide = false, closeDisabled = false, className = '' }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean; closeDisabled?: boolean; className?: string }) {
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
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''} ${className}`.trim()} onCancel={e => { if (closeDisabled) e.preventDefault(); }} onClick={e => {
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
