'use client';

import { Bell, Check, CircleCheck, LoaderCircle, RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import type { AnalysisMode, AnalysisModes } from '@/lib/types';
import { displaySeverities, sensitivityOptions } from '@/lib/workspace-preferences';
import type { NoticeKind, WorkspacePreferences } from '@/lib/workspace-preferences';
import './settings.css';

interface Props {
  config: AnalysisModes | null;
  loading: boolean;
  error: string | null;
  selectedMode: AnalysisMode | null;
  onChange: (mode: AnalysisMode) => void;
  onRetry: () => void;
  storageError: boolean;
  preferences: WorkspacePreferences;
  preferencesReady: boolean;
  onPreferences: (patch: Partial<WorkspacePreferences>) => void;
  desktopPermission: NotificationPermission | 'unsupported';
  desktopRequesting: boolean;
  onDesktop: () => void;
}

const riskLabels = { critical: 'Критические', warning: 'Требуют внимания', low: 'Низкий риск', ok: 'Без замечаний' };
const notices: { id: NoticeKind; title: string; description: string }[] = [
  { id: 'completed', title: 'Анализ завершён', description: 'Документы готовы к просмотру.' },
  { id: 'error', title: 'Ошибка проверки', description: 'Загрузка в очередь или обработка не удалась.' },
  { id: 'critical', title: 'Критические риски', description: 'В результатах есть критические замечания.' },
];

export function SettingsView({ config, loading, error, selectedMode, onChange, onRetry, storageError,
  preferences, preferencesReady, onPreferences, desktopPermission, desktopRequesting, onDesktop }: Props) {
  const selected = config?.modes.find(mode => mode.id === selectedMode);
  const desktopEnabled = preferences.notifications.desktop && desktopPermission === 'granted';
  return <section className="secondary-view settings-view">
    <div className="view-title settings-title">
      <div><h1>Настройки</h1><p>Проверка документов и отображение результатов.</p></div>
      <span className="settings-autosave"><CircleCheck size={14} />Автосохранение</span>
    </div>
    <div className="settings-grid">
      <section className="settings-card" aria-labelledby="mode-card-title">
        <div className="settings-card-heading"><span className="settings-card-icon"><ShieldCheck size={17} /></span><h2 id="mode-card-title">Режим анализа</h2><small>01</small></div>
        <p className="settings-card-description">Как система проверяет документы.</p>
        <fieldset className="settings-fieldset" disabled={loading || Boolean(error)}>
          <legend className="sr-only">Режим анализа</legend>
          {loading && <p className="settings-status" role="status"><LoaderCircle size={15} className="spin" />Загружаем режимы…</p>}
          {!error && config?.modes.map(mode => <label key={mode.id} className={`settings-choice${mode.id === selectedMode ? ' is-selected' : ''}${!mode.available ? ' is-unavailable' : ''}`}>
            <input type="radio" name="analysis-mode" value={mode.id} checked={mode.id === selectedMode} disabled={!mode.available} onChange={() => onChange(mode.id)} />
            <span><strong>{mode.id === 'llm' ? 'ИИ-анализ' : mode.label}{!mode.available && <small>Недоступен</small>}</strong><span>{mode.id === 'llm' ? 'Проверка смысла условий и возможных рисков.' : mode.id === 'keyword' ? 'Поиск фрагментов для ручной проверки.' : 'Выберите другой доступный режим.'}</span></span>
            {mode.id === selectedMode && <Check size={15} />}
          </label>)}
        </fieldset>
        {error && <div className="settings-error" role="alert"><p>Не удалось загрузить режимы.</p><button className="secondary-button" onClick={onRetry}><RefreshCw size={14} />Повторить</button></div>}
        {!loading && !error && selectedMode && !selected?.available && <p className="settings-warning" role="alert">Выберите доступный режим, чтобы запустить анализ.</p>}
        {config?.configuredModel && !error && <p className="settings-model">Модель: {config.configuredModel}</p>}
      </section>
      <section className="settings-card" aria-labelledby="risk-card-title">
        <div className="settings-card-heading"><span className="settings-card-icon"><SlidersHorizontal size={17} /></span><h2 id="risk-card-title">Уровни риска</h2><small>02</small></div>
        <p className="settings-card-description">Какие результаты показывать при открытии документа.</p>
        <fieldset className="settings-fieldset" disabled={!preferencesReady}>
          <legend className="sr-only">Уровни риска по умолчанию</legend>
          <div className="settings-risk-levels">{displaySeverities.map(level => <label key={level} className={`settings-risk-choice ${level}${preferences.defaultSeverities.includes(level) ? ' is-selected' : ''}`}>
            <input type="checkbox" checked={preferences.defaultSeverities.includes(level)} disabled={preferences.defaultSeverities.length === 1 && preferences.defaultSeverities[0] === level}
              onChange={event => onPreferences({ defaultSeverities: event.target.checked ? [...preferences.defaultSeverities, level] : preferences.defaultSeverities.filter(value => value !== level) })} />
            <i aria-hidden="true" /><span>{riskLabels[level]}</span>
          </label>)}</div>
        </fieldset>
        <p className="settings-card-note">Изначально выбраны все уровни. Полный набор результатов всегда доступен в фильтре документа.</p>
      </section>
      <section className="settings-card" aria-labelledby="sensitivity-card-title">
        <div className="settings-card-heading"><span className="settings-card-icon"><SlidersHorizontal size={17} /></span><h2 id="sensitivity-card-title">Чувствительность</h2><small>03</small></div>
        <p className="settings-card-description">Внимание к потенциальным нарушениям.</p>
        <fieldset className="settings-fieldset" disabled={!preferencesReady}>
          <legend className="sr-only">Чувствительность проверки</legend>
          {sensitivityOptions.map(option => <label key={option.id} className={`settings-choice${preferences.sensitivity === option.id ? ' is-selected' : ''}`}>
            <input type="radio" name="analysis-sensitivity" value={option.id} checked={preferences.sensitivity === option.id} onChange={() => onPreferences({ sensitivity: option.id })} />
            <span><strong>{option.label}</strong><span>{option.description}</span></span>{preferences.sensitivity === option.id && <Check size={15} />}
          </label>)}
        </fieldset>
        <p className="settings-card-note">Применяется при следующем запуске и повторной проверке.{selectedMode === 'keyword' && ' В поиске по словам меняется широта совпадений.'}</p>
      </section>
      <section className="settings-card" aria-labelledby="notifications-card-title">
        <div className="settings-card-heading"><span className="settings-card-icon"><Bell size={17} /></span><h2 id="notifications-card-title">Уведомления</h2><small>04</small></div>
        <p className="settings-card-description">Сообщения о результатах и проблемах проверки.</p>
        <fieldset className="settings-fieldset" disabled={!preferencesReady}>
          <legend className="sr-only">События для уведомлений</legend>
          {notices.map(notice => <label key={notice.id} className="settings-notification-row">
            <span><strong>{notice.title}</strong><span>{notice.description}</span></span>
            <input type="checkbox" className="settings-switch" checked={preferences.notifications[notice.id]} onChange={event => onPreferences({ notifications: { ...preferences.notifications, [notice.id]: event.target.checked } })} />
          </label>)}
        </fieldset>
        <div className="settings-desktop-row"><span>Уведомления браузера</span><button type="button" className="secondary-button" disabled={!preferencesReady || desktopRequesting || desktopPermission === 'unsupported' || desktopPermission === 'denied'} onClick={onDesktop}>
          {desktopRequesting ? 'Подключаем…' : desktopPermission === 'unsupported' ? 'Недоступны' : desktopPermission === 'denied' ? 'Заблокированы' : desktopEnabled ? 'Выключить' : 'Включить'}
        </button></div>
        <p className="settings-card-note">Уведомления приходят, пока сайт открыт.{desktopPermission === 'denied' && ' Разрешение можно изменить в настройках браузера.'}</p>
      </section>
    </div>
    <p className={`settings-save-note${storageError ? ' has-error' : ''}`} role="status">{storageError ? 'Браузер не разрешил сохранить настройки. Изменения действуют до перезагрузки страницы.' : 'Настройки автоматически сохраняются в этом браузере.'}</p>
  </section>;
}
