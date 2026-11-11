'use client';

import { useEffect, useState } from 'react';
import { Check, LoaderCircle, ScanText } from 'lucide-react';
import { errorMessage } from '@/lib/api';
import { MAX_PROCESSING_SLA_SECONDS, parseQualitySettings } from '@/lib/quality-settings';
import type { QualitySettings, User } from '@/lib/types';

interface Props {
  user: User | null;
  onSave: (settings: QualitySettings) => Promise<User>;
}

export function QualitySettingsCard({ user, onSave }: Props) {
  const settings = user?.qualitySettings;
  const [ocrMinConfidence, setOcrMinConfidence] = useState(settings?.ocrMinConfidence.toString() ?? '');
  const [processingSlaSeconds, setProcessingSlaSeconds] = useState(settings?.processingSlaSeconds?.toString() ?? '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOcrMinConfidence(settings?.ocrMinConfidence.toString() ?? '');
    setProcessingSlaSeconds(settings?.processingSlaSeconds?.toString() ?? '');
  }, [user?.id, settings?.ocrMinConfidence, settings?.processingSlaSeconds]);

  const changed = ocrMinConfidence.trim() !== (settings?.ocrMinConfidence.toString() ?? '')
    || processingSlaSeconds.trim() !== (settings?.processingSlaSeconds?.toString() ?? '');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!settings || saving || !changed) return;
    setSaving(true); setSaved(false); setError(null);
    try {
      const result = await onSave(parseQualitySettings({ ocrMinConfidence, processingSlaSeconds }));
      if (!result.qualitySettings) throw new Error('Не удалось подтвердить сохранение настроек. Обновите страницу и попробуйте ещё раз.');
      setOcrMinConfidence(result.qualitySettings.ocrMinConfidence.toString());
      setProcessingSlaSeconds(result.qualitySettings.processingSlaSeconds?.toString() ?? '');
      setSaved(true);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setSaving(false); }
  }

  function edited() { setSaved(false); setError(null); }

  return <section className="settings-card settings-quality-card" aria-labelledby="quality-card-title">
    <div className="settings-card-heading"><span className="settings-card-icon"><ScanText size={17} /></span><h2 id="quality-card-title">Качество проверки</h2></div>
    <form onSubmit={submit} aria-busy={saving}>
      <fieldset className="settings-fieldset settings-profile-fields settings-quality-fields" disabled={!settings || saving}>
        <legend className="sr-only">Нормативы качества проверки</legend>
        <label htmlFor="quality-sla">Нормативное время <small>секунды</small>
          <input id="quality-sla" name="processing-sla-seconds" type="number" inputMode="numeric" min={1} max={MAX_PROCESSING_SLA_SECONDS} step={1} placeholder={settings ? 'Без норматива' : ''} value={processingSlaSeconds} onChange={event => { setProcessingSlaSeconds(event.target.value); edited(); }} />
        </label>
        <label htmlFor="quality-confidence">Требуемый уровень распознавания <small>%</small>
          <input id="quality-confidence" name="ocr-min-confidence" type="number" inputMode="decimal" required min={0} max={100} step="any" aria-describedby="quality-confidence-help" value={ocrMinConfidence} onChange={event => { setOcrMinConfidence(event.target.value); edited(); }} />
          <span id="quality-confidence-help" className="settings-input-hint">От 0 до 100 %. Страницы ниже этого уровня требуют ручной проверки.</span>
        </label>
      </fieldset>
      <div className="settings-profile-actions">
        <span className="settings-card-note">Норматив времени не применяется к повторной проверке готового текста.</span>
        <button type="submit" className="primary-button" disabled={!settings || saving || !changed || !ocrMinConfidence.trim()}>{saving ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}{saving ? 'Сохраняем…' : 'Сохранить'}</button>
      </div>
      {(!user || saved) && <p className="settings-profile-feedback" role="status">{!user ? 'Загружаем настройки качества…' : 'Настройки сохранены в профиле.'}</p>}
      {user && !settings && <p className="settings-profile-feedback has-error" role="status">Настройки качества недоступны. Обновите страницу или обратитесь к администратору.</p>}
      {error && <p className="settings-profile-feedback has-error" role="alert">{error}</p>}
    </form>
  </section>;
}
