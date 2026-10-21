'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Cpu, LoaderCircle, RefreshCw, Search, Star, X } from 'lucide-react';
import { filterAnalysisModels, modelProviderIcons } from '@/lib/analysis-models';
import type { AnalysisModel } from '@/lib/types';
import type { AnalysisModelsState } from './use-analysis-models';
import './analysis-model-selector.css';

export function ModelProviderIcon({ provider }: { provider: string }) {
  const source = modelProviderIcons[provider];
  return <span className="model-provider-icon" data-provider={provider} aria-hidden="true">{source
    ? <img src={source} width="28" height="28" alt="" />
    : <Cpu size={24} />}</span>;
}

export function AnalysisModelSelector({ state, disabled = false }: { state: AnalysisModelsState; disabled?: boolean }) {
  const { catalog, loading, error, selectedModel, selectModel, refresh } = state;
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [provider, setProvider] = useState('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const models = catalog?.models ?? [];
  const selected = models.find(model => model.id === selectedModel);
  const visible = filterAnalysisModels(models, query, provider);
  const activeIndex = visible.findIndex(model => model.available && model.id === activeId);
  const fallbackIndex = visible.findIndex(model => model.available && model.id === selectedModel);
  const index = activeIndex >= 0 ? activeIndex : fallbackIndex >= 0 ? fallbackIndex : visible.findIndex(model => model.available);
  const providers = Array.from(new Map(models.map(model => [model.providerId, model.provider])).entries());
  const blocked = disabled || loading || Boolean(error);
  const expanded = open && !blocked;

  useEffect(() => {
    if (!expanded) return;
    search.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [expanded]);

  useEffect(() => {
    if (expanded && index >= 0) document.getElementById(`${id}-option-${index}`)?.scrollIntoView({ block: 'nearest' });
  }, [expanded, index, id, query, provider]);

  function close(restoreFocus = false) {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus();
  }
  function choose(model: AnalysisModel) {
    if (!model.available) return;
    selectModel(model.id);
    close(true);
  }
  function show() {
    setQuery('');
    setProvider('all');
    setActiveId(selectedModel);
    setOpen(true);
  }
  function move(direction: 1 | -1 | 'first' | 'last') {
    const positions = visible.flatMap((model, position) => model.available ? [position] : []);
    if (!positions.length) return;
    const current = positions.indexOf(index);
    const next = direction === 'first' ? positions[0] : direction === 'last' ? positions.at(-1)!
      : positions[(current + direction + positions.length) % positions.length];
    setActiveId(visible[next].id);
  }

  return <div className="analysis-model-picker" ref={root} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close();
  }} onKeyDown={event => {
    if (event.key === 'Escape' && expanded) { event.preventDefault(); event.stopPropagation(); close(true); }
  }}>
    <label id={`${id}-label`} className="model-picker-label">Модель ИИ</label>
    <button ref={trigger} type="button" className={`model-picker-trigger${expanded ? ' is-open' : ''}`}
      aria-labelledby={`${id}-label ${id}-value`} aria-haspopup="dialog" aria-expanded={expanded}
      aria-controls={expanded ? `${id}-dialog` : undefined} disabled={blocked}
      onClick={() => expanded ? close() : show()} onKeyDown={event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); show(); }
      }}>
      {loading ? <LoaderCircle size={22} className="spin" /> : <ModelProviderIcon provider={selected?.providerId ?? 'other'} />}
      <span className="model-picker-value" id={`${id}-value`}>{loading ? 'Загружаем модели…' : selected?.label ?? selectedModel ?? 'Выберите модель'}{selected && <small>{selected.provider}</small>}</span>
      <ChevronDown size={18} className="model-picker-chevron" />
    </button>
    {error && <div className="model-picker-feedback is-error" role="alert"><p>{error}</p><button type="button" onClick={refresh} disabled={disabled}><RefreshCw size={14} />Повторить</button></div>}
    {expanded && <div id={`${id}-dialog`} className="model-picker-panel" role="dialog" aria-label="Выбор модели ИИ">
      <div className="model-picker-search"><Search size={17} aria-hidden="true" />
        <input ref={search} role="combobox" aria-label="Найти модель" placeholder="Найти модель…" value={query}
          aria-autocomplete="list" aria-expanded="true" aria-controls={`${id}-list`}
          aria-activedescendant={index >= 0 ? `${id}-option-${index}` : undefined}
          onChange={event => { setQuery(event.target.value); setActiveId(null); }}
          onKeyDown={event => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); move(event.key === 'ArrowDown' ? 1 : -1); }
            if ((event.ctrlKey || event.metaKey) && (event.key === 'Home' || event.key === 'End')) { event.preventDefault(); move(event.key === 'Home' ? 'first' : 'last'); }
            if (event.key === 'Enter') { event.preventDefault(); if (index >= 0) choose(visible[index]); }
          }} />
        {query && <button type="button" aria-label="Очистить поиск моделей" onClick={() => { setQuery(''); search.current?.focus(); }}><X size={15} /></button>}
      </div>
      <div className="model-picker-filters" role="group" aria-label="Провайдер модели">
        {[['all', 'Все модели'], ...providers].map(([value, label]) => <button key={value} type="button" aria-pressed={provider === value}
          onClick={() => { setProvider(value); setActiveId(null); }}>{label}</button>)}
      </div>
      <div id={`${id}-list`} className="model-picker-options" role="listbox" aria-label="Модели ИИ">
        {visible.map((model, position) => <button key={model.id} type="button" id={`${id}-option-${position}`} role="option" tabIndex={-1}
          aria-selected={model.id === selectedModel} aria-disabled={!model.available}
          className={`model-picker-option${model.id === selectedModel ? ' is-selected' : ''}${position === index ? ' is-active' : ''}`}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(model)}>
          <ModelProviderIcon provider={model.providerId} />
          <span className="model-option-copy"><span className="model-option-title"><strong>{model.label}</strong><small>{model.provider}</small></span><span>{model.description}</span></span>
          <span className="model-option-state">{model.recommended && <span className="model-recommended"><Star size={12} fill="currentColor" />Рекомендуется</span>}
            {!model.available ? <small>Недоступна</small> : model.id === selectedModel ? <Check size={18} /> : <i className="model-option-radio" />}</span>
        </button>)}
      </div>
      {!visible.length && <p className="model-picker-empty" role="status">Модели не найдены. Попробуйте другой запрос или провайдера.</p>}
      <span className="sr-only" role="status">Найдено моделей: {visible.length}</span>
    </div>}
    {!loading && !error && selectedModel && !selected?.available && <p className="model-picker-feedback is-error" role="alert">Выбранная модель недоступна. Выберите другую модель.</p>}
    {catalog?.warning && !error && <p className="model-picker-feedback" role="status">{catalog.warning} <button type="button" onClick={refresh} disabled={loading}>Обновить</button></p>}
    <p className="model-picker-note">Применится при следующем запуске и повторной проверке.</p>
  </div>;
}
