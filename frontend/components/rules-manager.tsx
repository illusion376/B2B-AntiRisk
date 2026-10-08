'use client';

import { useRef, useState } from 'react';
import { AlertTriangle, BookOpenCheck, LoaderCircle, Pencil, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react';
import type { CheckRule, RuleDraft, RiskLevel } from '@/lib/types';
import { compareRulesByRisk, riskLabels } from '@/lib/rules';
import { IconButton, Modal } from './ui';

type RulesManagerProps = {
  rules: CheckRule[];
  onAdd: () => void;
  onEdit: (rule: CheckRule) => void;
  onDelete: (rule: CheckRule) => void;
  onToggle: (rule: CheckRule) => Promise<void>;
  pendingRuleId?: string | null;
  error?: string | null;
};

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function RulesManager({
  rules,
  onAdd,
  onEdit,
  onDelete,
  onToggle,
  pendingRuleId = null,
  error = null,
}: RulesManagerProps) {
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState('all');
  const [localError, setLocalError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const pendingRef = useRef(new Set<string>());
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const filtered = rules.filter(rule => (
    `${rule.title} ${rule.description} ${rule.category}`.toLocaleLowerCase('ru').includes(normalizedQuery)
    && (level === 'all' || rule.severity === level)
  )).sort(compareRulesByRisk);
  const displayedError = localError || error;

  async function toggleRule(rule: CheckRule) {
    if (pendingRef.current.has(rule.id) || pendingRuleId === rule.id) return;
    pendingRef.current.add(rule.id);
    setPendingIds(new Set(pendingRef.current));
    setLocalError(null);
    try {
      await onToggle(rule);
    } catch (cause) {
      setLocalError(getErrorMessage(cause, 'Не удалось изменить правило. Попробуйте ещё раз.'));
    } finally {
      pendingRef.current.delete(rule.id);
      setPendingIds(new Set(pendingRef.current));
    }
  }

  return (
    <section className="secondary-view rules-view">
      <div className="view-title">
        <div>
          <span className="eyebrow">НАСТРОЙКА ПРОВЕРКИ</span>
          <h1>Правила проверки</h1>
          <p>Создавайте свои правила и определяйте степень риска.</p>
        </div>
        <button type="button" className="primary-button" onClick={onAdd}>
          <Plus size={18} />Добавить правило
        </button>
      </div>
      <div className="rules-toolbar">
        <label className="field-search">
          <Search size={18} />
          <input
            placeholder="Найти правило..."
            aria-label="Найти правило"
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </label>
        <select
          className="form-select rule-risk-filter"
          aria-label="Фильтр правил по риску"
          value={level}
          onChange={event => setLevel(event.target.value)}
        >
          <option value="all">Все степени риска</option>
          {Object.entries(riskLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <span className="count-chip">
          <ShieldCheck size={16} />{rules.filter(rule => rule.enabled).length} из {rules.length} включено
        </span>
      </div>
      {displayedError && <p className="field-error" role="alert">{displayedError}</p>}
      {filtered.length > 0 && (
        <div className="dashboard-table-scroll">
          <table className="dashboard-project-table dashboard-rules-table">
            <thead>
              <tr>
                <th scope="col">Правило</th>
                <th scope="col">Категория</th>
                <th scope="col" aria-sort="descending">Степень риска</th>
                <th scope="col">Активно</th>
                <th scope="col"><span className="sr-only">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(rule => {
                const pending = pendingIds.has(rule.id) || pendingRuleId === rule.id;
                return (
                  <tr key={rule.id} aria-busy={pending}>
                    <td>
                      <button
                        type="button"
                        className="dashboard-rule-title"
                        disabled={pending}
                        onClick={() => onEdit(rule)}
                      >
                        <strong>{rule.title}</strong>
                        <small>{rule.description || 'Описание не добавлено.'}</small>
                      </button>
                    </td>
                    <td><span className="dashboard-rule-category">{rule.category}</span></td>
                    <td><span className={`severity-tag ${rule.severity}`}>{riskLabels[rule.severity]}</span></td>
                    <td>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={rule.enabled}
                        aria-label={`Правило: ${rule.title}${pending ? '. Сохранение' : ''}`}
                        className="switch"
                        disabled={pending}
                        onClick={() => void toggleRule(rule)}
                      ><span /></button>
                    </td>
                    <td>
                      <div className="dashboard-rule-actions">
                        <IconButton
                          label={`Редактировать правило «${rule.title}»`}
                          disabled={pending}
                          onClick={() => onEdit(rule)}
                        ><Pencil size={15} /></IconButton>
                        <IconButton
                          className="delete-rule-button"
                          label={`Удалить правило «${rule.title}»`}
                          disabled={pending}
                          onClick={() => onDelete(rule)}
                        ><Trash2 size={15} /></IconButton>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {!filtered.length && (
        <div className="empty-state">
          <BookOpenCheck size={32} />
          <h3>{rules.length ? 'Правила не найдены' : 'Пока нет правил'}</h3>
          <p>{rules.length ? 'Измените запрос или степень риска.' : 'Добавьте первое правило для проверки документов.'}</p>
          {!rules.length && (
            <button type="button" className="primary-button" onClick={onAdd}>
              <Plus size={16} />Добавить правило
            </button>
          )}
        </div>
      )}
    </section>
  );
}

type RuleEditorProps = {
  rule: CheckRule | null;
  categories: string[];
  onSave: (draft: RuleDraft) => Promise<string | void>;
  onClose: () => void;
};

export function RuleEditor({ rule, categories, onSave, onClose }: RuleEditorProps) {
  // Omit advanced settings from PATCH so the server preserves custom settings and
  // can update automatically generated prompts when the title or description changes.
  const [draft, setDraft] = useState<RuleDraft>(() => rule ? {
    title: rule.title,
    description: rule.description,
    category: rule.category,
    severity: rule.severity,
    enabled: rule.enabled,
  } : {
    title: '',
    description: '',
    category: 'Общие условия',
    severity: 'warning',
    enabled: true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const valid = Boolean(draft.title.trim() && draft.category.trim());

  function close() {
    if (!savingRef.current) onClose();
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      const message = await onSave({
        ...draft,
        title: draft.title.trim(),
        description: draft.description.trim(),
        category: draft.category.trim(),
      });
      if (message) setError(message);
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось сохранить правило. Попробуйте ещё раз.'));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <Modal title={rule ? 'Редактировать правило' : 'Добавить правило'} onClose={close} closeDisabled={saving}>
      <form onSubmit={event => void save(event)} aria-busy={saving}>
        <label className="form-label" htmlFor="rule-title">Название правила <span aria-hidden="true">*</span></label>
        <input
          className="form-input"
          id="rule-title"
          autoFocus
          required
          disabled={saving}
          maxLength={120}
          placeholder="Например, срок оплаты"
          value={draft.title}
          onChange={event => setDraft({ ...draft, title: event.target.value })}
        />
        <label className="form-label" htmlFor="rule-description">Описание</label>
        <textarea
          className="form-input"
          id="rule-description"
          rows={3}
          disabled={saving}
          maxLength={1000}
          placeholder="Что необходимо проверить в документе"
          value={draft.description}
          onChange={event => setDraft({ ...draft, description: event.target.value })}
        />
        <label className="form-label" htmlFor="rule-category">Категория <span aria-hidden="true">*</span></label>
        <input
          className="form-input"
          id="rule-category"
          list="rule-categories"
          required
          disabled={saving}
          maxLength={60}
          value={draft.category}
          onChange={event => setDraft({ ...draft, category: event.target.value })}
        />
        <datalist id="rule-categories">
          {categories.map(category => <option key={category} value={category} />)}
        </datalist>
        <fieldset className="risk-choices" disabled={saving}>
          <legend className="form-label">Степень риска</legend>
          {Object.entries(riskLabels).map(([value, label]) => (
            <label key={value} className={`risk-choice ${value} ${draft.severity === value ? 'selected' : ''}`}>
              <input
                type="radio"
                name="rule-risk"
                value={value}
                checked={draft.severity === value}
                onChange={() => setDraft({ ...draft, severity: value as RiskLevel })}
              />
              <span className={`risk-dot ${value}`} />{label}
            </label>
          ))}
        </fieldset>
        <label className="rule-enable-field">
          <input
            type="checkbox"
            disabled={saving}
            checked={draft.enabled}
            onChange={event => setDraft({ ...draft, enabled: event.target.checked })}
          />
          Использовать правило при проверке
        </label>
        <p className="form-hint">{rule
          ? 'Изменения применятся при следующей проверке документов.'
          : 'Новое правило будет применяться при следующих проверках документов.'}</p>
        {error && <p className="field-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" disabled={saving} onClick={close}>Отмена</button>
          <button type="submit" className="primary-button" disabled={!valid || saving}>
            {saving && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
            {saving ? 'Сохранение…' : rule ? 'Сохранить изменения' : 'Добавить правило'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

type DeleteRuleDialogProps = {
  rule: CheckRule;
  onConfirm: () => Promise<string | void>;
  onClose: () => void;
};

export function DeleteRuleDialog({ rule, onConfirm, onClose }: DeleteRuleDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingRef = useRef(false);

  function close() {
    if (!pendingRef.current) onClose();
  }

  async function confirm() {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setError(null);
    try {
      const message = await onConfirm();
      if (message) setError(message);
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось удалить правило. Попробуйте ещё раз.'));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  return (
    <Modal title="Точно удалить?" onClose={close} closeDisabled={pending}>
      <div className="delete-rule-intro">
        <span><AlertTriangle size={24} /></span>
        <p>Правило <strong>«{rule.title}»</strong> и связанные с ним замечания будут удалены. Отменить это действие нельзя.</p>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="modal-actions" aria-busy={pending}>
        <button type="button" autoFocus className="secondary-button" disabled={pending} onClick={close}>Отмена</button>
        <button type="button" className="primary-button" disabled={pending} onClick={() => void confirm()}>
          {pending ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <Trash2 size={16} />}
          {pending ? 'Удаление…' : 'Удалить правило'}
        </button>
      </div>
    </Modal>
  );
}
