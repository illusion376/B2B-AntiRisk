'use client';

import { Check, LoaderCircle, RefreshCw, Settings2 } from 'lucide-react';
import type { AnalysisMode, AnalysisModes } from '@/lib/types';
import './settings.css';

interface Props {
  config: AnalysisModes | null;
  loading: boolean;
  error: string | null;
  selectedMode: AnalysisMode | null;
  onChange: (mode: AnalysisMode) => void;
  onRetry: () => void;
  storageError: boolean;
}

export function SettingsView({ config, loading, error, selectedMode, onChange, onRetry, storageError }: Props) {
  const selected = config?.modes.find(mode => mode.id === selectedMode);
  return (
    <section className="secondary-view settings-view">
      <div className="view-title">
        <div><span className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Настройки</h1><p>Выберите способ проверки документов для всех проектов.</p></div>
        <span className="settings-heading-icon"><Settings2 size={24} /></span>
      </div>
      <div className="analysis-settings-card">
        <fieldset className="analysis-mode-fieldset" disabled={loading || Boolean(error)} aria-describedby="analysis-settings-help">
          <legend>Режим анализа</legend>
          <p id="analysis-settings-help">Применяется при запуске и повторной проверке. Уже запущенный анализ продолжится в выбранном для него режиме.</p>
          {loading && <p className="settings-status" role="status"><LoaderCircle size={17} className="spin" />Загружаем доступные режимы…</p>}
          {!error && <div className="analysis-mode-options">
            {config?.modes.map(mode => (
              <label key={mode.id} className={`analysis-mode-option ${mode.id === selectedMode ? 'is-selected' : ''} ${!mode.available ? 'is-unavailable' : ''}`}>
                <input type="radio" name="analysis-mode" value={mode.id} checked={mode.id === selectedMode} disabled={!mode.available} onChange={() => onChange(mode.id)} />
                <span className="analysis-mode-copy"><strong>{mode.label}{!mode.available && <small>Недоступен</small>}</strong><span>{mode.description}</span></span>
                {mode.id === selectedMode && <Check size={19} aria-hidden="true" />}
              </label>
            ))}
          </div>}
        </fieldset>
        {error && <div className="settings-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={onRetry}><RefreshCw size={15} />Повторить</button></div>}
        {!loading && !error && selectedMode && !selected?.available && <p className="settings-warning" role="alert">Выбранный режим недоступен. Выберите доступный вариант, чтобы запустить проверку.</p>}
        {config?.configuredModel && !error && <p className="settings-model">Модель: <strong>{config.configuredModel}</strong></p>}
        <p className="settings-save-note" role="status">{storageError ? 'Браузер не разрешил сохранить настройку. Выбор действует до перезагрузки страницы.' : 'Выбор сохраняется автоматически в этом браузере.'}</p>
      </div>
    </section>
  );
}
