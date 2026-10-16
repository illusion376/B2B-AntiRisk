'use client';

import { useEffect, useState } from 'react';
import { Check, LoaderCircle, UserRound } from 'lucide-react';
import { errorMessage } from '@/lib/api';
import type { User, UserProfileDraft } from '@/lib/types';

interface Props {
  user: User | null;
  onSave: (draft: UserProfileDraft) => Promise<User>;
}

export function ReportProfileSettings({ user, onSave }: Props) {
  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [companyName, setCompanyName] = useState(user?.companyName ?? '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setFullName(user?.fullName ?? '');
    setCompanyName(user?.companyName ?? '');
  }, [user?.id, user?.fullName, user?.companyName]);
  const changed = fullName.trim() !== (user?.fullName ?? '') || companyName.trim() !== (user?.companyName ?? '');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!user || saving || !fullName.trim() || !changed) return;
    setSaving(true); setSaved(false); setError(null);
    try {
      const result = await onSave({ fullName, companyName });
      setFullName(result.fullName); setCompanyName(result.companyName ?? ''); setSaved(true);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setSaving(false); }
  }
  function edited() { setSaved(false); setError(null); }

  return <section className="settings-card settings-profile-card" aria-labelledby="profile-card-title">
    <div className="settings-card-heading"><span className="settings-card-icon"><UserRound size={17} /></span><h2 id="profile-card-title">Данные для отчёта</h2></div>
    <p id="profile-card-help" className="settings-card-description">Ваше имя и компания будут указаны в новых отчётах.</p>
    <form onSubmit={submit} aria-describedby="profile-card-help" aria-busy={saving}>
      <fieldset className="settings-fieldset settings-profile-fields" disabled={!user || saving}>
        <legend className="sr-only">Имя и компания</legend>
        <label htmlFor="report-author">Имя<input id="report-author" name="name" autoComplete="name" required maxLength={255} placeholder="Иван Иванов" value={fullName} onChange={event => { setFullName(event.target.value); edited(); }} /></label>
        <label htmlFor="report-company">Компания <small>необязательно</small><input id="report-company" name="organization" autoComplete="organization" maxLength={255} placeholder="ООО «Компания»" value={companyName} onChange={event => { setCompanyName(event.target.value); edited(); }} /></label>
      </fieldset>
      <div className="settings-profile-actions">
        <span className="settings-card-note">Для отчётов используются сохранённые данные.</span>
        <button type="submit" className="primary-button" disabled={!user || saving || !changed || !fullName.trim()}>{saving ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}{saving ? 'Сохраняем…' : 'Сохранить'}</button>
      </div>
      {(!user || saved) && <p className="settings-profile-feedback" role="status">{!user ? 'Загружаем данные профиля…' : 'Данные сохранены на сервере.'}</p>}
      {error && <p className="settings-profile-feedback has-error" role="alert">{error}</p>}
    </form>
  </section>;
}
