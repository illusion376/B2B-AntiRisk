'use client';

import { useId } from 'react';
import { AlertCircle, Check, LoaderCircle, RefreshCw } from 'lucide-react';
import type { AnalysisMode, AnalysisModeOption } from '@/lib/types';
import './analysis-mode-selector.css';

interface AnalysisModeSelectorProps {
  modes: AnalysisModeOption[];
  selectedMode: AnalysisMode | null;
  onChange: (mode: AnalysisMode) => void;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  configuredModel: string | null;
  disabled?: boolean;
}

export function AnalysisModeSelector({ modes, selectedMode, onChange, loading, error, onRetry, configuredModel, disabled = false }: AnalysisModeSelectorProps) {
  const id = useId();
  const selected = modes.find(mode => mode.id === selectedMode);

  return (
    <section className="analysis-mode-selector" aria-label="Режим анализа">
      <div className="analysis-mode-heading">
        <h3>Режим анализа</h3>
        <span>Применится при запуске проверки</span>
      </div>
      {loading ? (
        <p className="analysis-mode-feedback" role="status"><LoaderCircle size={15} className="spin" />Проверяем доступные режимы…</p>
      ) : error ? (
        <div className="analysis-mode-feedback is-error" role="alert">
          <AlertCircle size={16} /><p>{error}</p>
          <button type="button" className="secondary-button" onClick={onRetry} disabled={disabled}><RefreshCw size={14} />Повторить</button>
        </div>
      ) : (
        <>
          <fieldset className="analysis-mode-options" disabled={disabled} aria-describedby={`${id}-help`}>
            <legend className="sr-only">Выберите режим анализа</legend>
            {modes.map(mode => (
              <label key={mode.id} className={`analysis-mode-option ${selectedMode === mode.id ? 'is-selected' : ''} ${!mode.available ? 'is-unavailable' : ''}`}>
                <input type="radio" name={id} value={mode.id} checked={selectedMode === mode.id} onChange={() => onChange(mode.id)} />
                <span className="analysis-mode-option-copy">
                  <span className="analysis-mode-option-title"><strong>{mode.label}</strong>{!mode.available && <small>Недоступен</small>}</span>
                  <span>{mode.description}</span>
                </span>
                {selectedMode === mode.id && <Check size={16} className="analysis-mode-check" aria-hidden="true" />}
              </label>
            ))}
          </fieldset>
          <div className={`analysis-mode-help ${selected && !selected.available ? 'is-unavailable' : ''}`} id={`${id}-help`} role="status">
            {selected && !selected.available ? (
              <><AlertCircle size={15} /><p>{selected.id === 'llm'
                ? 'LLM недоступен. Настройте модель и доступ к ней на сервере, затем обновите доступность режимов.'
                : 'Выбранный режим недоступен на сервере. Настройте его или выберите другой режим.'} Автоматической замены режима не будет.</p>
                <button type="button" onClick={onRetry} disabled={disabled}>Обновить доступность</button></>
            ) : !selected ? <p>Выберите режим для запуска анализа.</p>
              : selected.id === 'llm' && configuredModel ? <p>Модель: <strong>{configuredModel}</strong></p>
              : <p>Документы будут проверены выбранным способом после нажатия кнопки запуска.</p>}
          </div>
        </>
      )}
    </section>
  );
}
