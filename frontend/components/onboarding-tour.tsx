'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowRight, ChevronLeft, LoaderCircle, X } from 'lucide-react';
import type { TourStep } from '@/lib/onboarding';
import './onboarding-tour.css';

interface Props {
  step: TourStep;
  intro: boolean;
  paused: boolean;
  onClose: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
}
interface Position { top: number; left: number; width: number; height: number }
interface Layout { spotlight: Position; card: Position; side: 'top' | 'bottom' | 'right'; arrow: number; canAct: boolean }

export function OnboardingTour({ step, intro, paused, onClose, onNext, onPrevious }: Props) {
  const id = useId();
  const cardRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const callbacks = useRef({ onClose, onNext });
  callbacks.current = { onClose, onNext };
  const [layout, setLayout] = useState<Layout | null>(null);
  const initialFocus = useRef<Element | null>(null);

  useEffect(() => {
    initialFocus.current = document.activeElement;
    return () => {
      const previous = initialFocus.current;
      if (previous instanceof HTMLElement && previous.isConnected && !document.querySelector('dialog[open]')) previous.focus({ preventScroll: true });
    };
  }, []);

  useLayoutEffect(() => {
    if (paused) { setLayout(null); return; }
    let frame = 0;
    let current: HTMLElement | null = null;
    let scrolled = false;
    const activate = () => { if (intro) callbacks.current.onNext?.(); };
    const measure = () => {
      frame = 0;
      if (document.querySelector('dialog[open]')) { setLayout(null); return; }
      const candidates = [step.target, step.fallback].filter((value): value is string => Boolean(value));
      const target = candidates.map(selector => document.querySelector<HTMLElement>(selector)).find(element => {
        if (!element) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
      }) ?? null;
      if (target !== current) {
        current?.removeEventListener('click', activate);
        current = target;
        targetRef.current = target;
        current?.addEventListener('click', activate);
        scrolled = false;
      }
      if (!target) { setLayout(null); return; }
      if (!scrolled) { target.scrollIntoView({ block: 'nearest', inline: 'nearest' }); scrolled = true; }
      const rect = target.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const left = Math.max(4, rect.left - 6);
      const top = Math.max(4, rect.top - 6);
      const right = Math.min(viewportWidth - 4, rect.right + 6);
      const bottom = Math.min(viewportHeight - 4, rect.bottom + 6);
      if (right <= left || bottom <= top) { setLayout(null); return; }
      const width = Math.min(340, viewportWidth - 24);
      const height = cardRef.current?.getBoundingClientRect().height || 245;
      const gap = 14;
      let side: Layout['side'] = 'bottom';
      let cardLeft = Math.max(12, Math.min(viewportWidth - width - 12, left));
      let cardTop = bottom + gap;
      if (step.placement === 'right' && right + gap + width <= viewportWidth - 12) {
        side = 'right'; cardLeft = right + gap; cardTop = Math.max(12, Math.min(viewportHeight - height - 12, top));
      } else if (cardTop + height > viewportHeight - 12 && top - gap - height >= 12) {
        side = 'top'; cardTop = top - gap - height;
      } else cardTop = Math.max(12, Math.min(viewportHeight - height - 12, cardTop));
      const arrow = side === 'right' ? Math.max(22, Math.min(height - 22, (top + bottom) / 2 - cardTop))
        : Math.max(22, Math.min(width - 22, (left + right) / 2 - cardLeft));
      setLayout({ spotlight: { left, top, width: right - left, height: bottom - top },
        card: { left: cardLeft, top: cardTop, width, height }, side, arrow,
        canAct: target instanceof HTMLButtonElement && !target.disabled && !step.waiting });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const observer = new MutationObserver(schedule);
    observer.observe(document.querySelector('.dashboard-shell') ?? document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'disabled', 'hidden', 'open'] });
    const resize = new ResizeObserver(schedule);
    if (cardRef.current) resize.observe(cardRef.current);
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    window.addEventListener('transitionend', schedule, true);
    measure();
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); resize.disconnect();
      current?.removeEventListener('click', activate);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
      window.removeEventListener('transitionend', schedule, true);
      targetRef.current = null;
    };
  }, [step.id, step.target, step.fallback, step.placement, step.waiting, intro, paused]);

  useEffect(() => {
    if (paused || !layout) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopPropagation(); callbacks.current.onClose();
    };
    window.addEventListener('keydown', escape, true);
    return () => window.removeEventListener('keydown', escape, true);
  }, [paused, Boolean(layout)]);

  const focusedStep = useRef('');
  useEffect(() => {
    if (paused || !layout || focusedStep.current === step.id) return;
    focusedStep.current = step.id;
    headingRef.current?.focus({ preventScroll: true });
  }, [step.id, paused, Boolean(layout)]);

  if (typeof document === 'undefined') return null;
  const spotlight = layout?.spotlight;
  return createPortal(<div className="onboarding-tour" hidden={paused || !layout}>
    {spotlight && <>
      <div className="onboarding-spotlight" style={spotlight} />
      <div className="onboarding-shade" style={{ top: 0, left: 0, right: 0, height: spotlight.top }} />
      <div className="onboarding-shade" style={{ top: spotlight.top + spotlight.height, left: 0, right: 0, bottom: 0 }} />
      <div className="onboarding-shade" style={{ top: spotlight.top, left: 0, width: spotlight.left, height: spotlight.height }} />
      <div className="onboarding-shade" style={{ top: spotlight.top, left: spotlight.left + spotlight.width, right: 0, height: spotlight.height }} />
    </>}
    {layout && <span className={`onboarding-arrow is-${layout.side}`} style={layout.side === 'right'
      ? { top: layout.card.top + layout.arrow - 6, left: layout.card.left - 6 }
      : { top: layout.side === 'bottom' ? layout.card.top - 6 : layout.card.top + layout.card.height - 7, left: layout.card.left + layout.arrow - 6 }} />}
    <section ref={cardRef} className="onboarding-card" role="dialog" aria-modal="false" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}
      style={layout ? { top: layout.card.top, left: layout.card.left, width: layout.card.width } : undefined}>
      <button type="button" className="onboarding-close" aria-label="Закрыть подсказки" onClick={onClose}><X size={17} /></button>
      <p className="onboarding-caption">{intro ? 'ЗНАКОМСТВО С ANTIRISK' : 'ТУР ПРОЕКТА'}</p>
      <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>{step.title}</h2>
      <p id={`${id}-description`} className="onboarding-description">{step.description}</p>
      <div className="onboarding-footer"><span>Шаг {step.number} из {step.total}</span>
        <div className="onboarding-actions">
          {onPrevious && <button type="button" className="onboarding-back" aria-label="Предыдущая подсказка" onClick={onPrevious}><ChevronLeft size={17} /></button>}
          <button type="button" className="onboarding-next" disabled={!onNext && !layout?.canAct} onClick={() => {
            if (onNext) onNext();
            else if (layout?.canAct) targetRef.current?.click();
          }}>{step.waiting && <LoaderCircle size={14} className="onboarding-spinner" />}{step.action}{!step.waiting && <ArrowRight size={14} />}</button>
        </div>
      </div>
      <button type="button" className="onboarding-skip" onClick={onClose}>Пропустить обучение</button>
    </section>
  </div>, document.body);
}
