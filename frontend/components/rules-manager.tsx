'use client';

import { useId, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSearch,
  FileText,
  Lightbulb,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { api } from '@/lib/api';
import { severityLabels } from '@/lib/labels';
import type { CheckRule, RiskLevel, RuleDraft, RuleTestResult } from '@/lib/types';
import { compareRulesByRisk, riskLabels } from '@/lib/rules';
import { CustomSelect, IconButton, Modal } from './ui';
import './rule-editor.css';

export interface RuleTestTargetDocument {
  id: string;
  name: string;
  projectTitle?: string;
  status: string;
  progress: number;
  phase?: string;
}

type RulesManagerProps = {
  rules: CheckRule[];
  documents?: RuleTestTargetDocument[];
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
        <CustomSelect
          ariaLabel="Фильтр правил по риску"
          className="rule-risk-filter"
          value={level}
          onChange={setLevel}
          options={[
            { value: 'all', label: 'Все степени риска' },
            ...Object.entries(riskLabels).map(([value, label]) => ({ value, label })),
          ]}
        />
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
                    <td data-label="Категория"><span className="dashboard-rule-category">{rule.category}</span></td>
                    <td data-label="Степень риска"><span className={`severity-tag ${rule.severity}`}>{riskLabels[rule.severity]}</span></td>
                    <td data-label="Активно">
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
                        <button
                          type="button"
                          className="dashboard-row-action"
                          aria-label={`Редактировать правило «${rule.title}»`}
                          title="Редактировать правило"
                          disabled={pending}
                          onClick={() => onEdit(rule)}
                        ><Pencil size={15} /></button>
                        <button
                          type="button"
                          className="dashboard-row-action delete-rule-button"
                          aria-label={`Удалить правило «${rule.title}»`}
                          title="Удалить правило"
                          disabled={pending}
                          onClick={() => onDelete(rule)}
                        ><Trash2 size={15} /></button>
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
  documents?: RuleTestTargetDocument[];
  initialDocumentId?: string | null;
  onSave: (draft: RuleDraft) => Promise<string | void>;
  onClose: () => void;
};

const defaultCategories = [
  'Общие условия',
  'Сроки и поставка',
  'Финансовые риски',
  'Штрафы и неустойки',
  'Расторжение контракта (РНП)',
  'Ответственность сторон',
  'Приёмка товаров и услуг',
  'Гарантийные обязательства',
];

export function RuleEditor({
  rule,
  categories,
  documents = [],
  initialDocumentId = null,
  onSave,
  onClose,
}: RuleEditorProps) {
  const availableCategories = Array.from(new Set([...categories, ...defaultCategories]));

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
  const [customMode, setCustomMode] = useState(
    draft.category.trim() !== '' && !availableCategories.includes(draft.category)
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const valid = Boolean(draft.title.trim() && draft.category.trim());

  // Состояние песочницы тестирования
  const [testSource, setTestSource] = useState<'document' | 'custom'>('document');
  const [selectedDocId, setSelectedDocId] = useState<string>(() => {
    if (initialDocumentId && documents.some(d => d.id === initialDocumentId)) {
      return initialDocumentId;
    }
    const readyDoc = documents.find(d => d.status === 'COMPLETED' || d.phase === 'ready');
    return readyDoc?.id || documents[0]?.id || '';
  });
  const [customSnippet, setCustomSnippet] = useState('');
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<RuleTestResult | null>(null);
  const [showFragments, setShowFragments] = useState(false);

  const selectedDocInfo = useMemo(() => {
    return documents.find(d => d.id === selectedDocId);
  }, [documents, selectedDocId]);

  const selectedDocReady = Boolean(
    selectedDocInfo && (selectedDocInfo.status === 'COMPLETED' || selectedDocInfo.phase === 'ready')
  );

  const canTest = Boolean(
    draft.title.trim() &&
    (testSource === 'document' ? selectedDocId && selectedDocReady : customSnippet.trim().length >= 10)
  );

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

  async function runTest() {
    if (!draft.title.trim()) {
      setTestError('Укажите название правила для проверки');
      return;
    }
    if (testSource === 'document') {
      if (!selectedDocId) {
        setTestError('Выберите документ для проверки');
        return;
      }
      if (!selectedDocReady) {
        setTestError(
          `Документ «${selectedDocInfo?.name || ''}» ещё обрабатывается (${selectedDocInfo?.progress || 0}%). Дождитесь завершения обработки.`
        );
        return;
      }
    } else {
      if (customSnippet.trim().length < 10) {
        setTestError('Введите фрагмент текста договора (не менее 10 символов)');
        return;
      }
    }

    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      const res = await api.previewRule(
        {
          title: draft.title.trim(),
          description: draft.description.trim(),
          category: draft.category.trim(),
          severity: draft.severity,
          enabled: draft.enabled,
        },
        {
          documentId: testSource === 'document' ? selectedDocId : undefined,
          customText: testSource === 'custom' ? customSnippet.trim() : undefined,
        }
      );
      setTestResult(res);
    } catch (cause) {
      setTestError(getErrorMessage(cause, 'Не удалось выполнить проверку правила.'));
    } finally {
      setTesting(false);
    }
  }

  return (
    <Modal
      title={rule ? 'Редактировать правило' : 'Добавить правило'}
      wide
      className="rule-editor-modal"
      onClose={close}
      closeDisabled={saving || testing}
    >
      <form onSubmit={event => void save(event)} aria-busy={saving || testing}>
        <div className="rule-editor-layout">
          {/* Левая колонка: форма параметров правила */}
          <div className="rule-editor-form">
            <label className="form-label" htmlFor="rule-title">
              Название правила <span aria-hidden="true">*</span>
            </label>
            <input
              className="form-input"
              id="rule-title"
              autoFocus
              required
              disabled={saving}
              maxLength={120}
              placeholder="Например, срок оплаты товара"
              value={draft.title}
              onChange={event => setDraft({ ...draft, title: event.target.value })}
            />

            <label className="form-label" htmlFor="rule-description">
              Описание риска
            </label>
            <textarea
              className="form-input"
              id="rule-description"
              rows={3}
              disabled={saving}
              maxLength={1000}
              placeholder="Что именно является нарушением (например: срок оплаты более 7 рабочих дней)"
              value={draft.description}
              onChange={event => setDraft({ ...draft, description: event.target.value })}
            />

            {/* Подсказки юристу по формулированию правила */}
            <details className="rule-hints-card">
              <summary>
                <Lightbulb size={14} /> Как сформулировать правило для точного поиска
              </summary>
              <div className="rule-hints-content">
                <ul>
                  <li>
                    <strong>Название:</strong> конкретизируйте предмет условия (например, <em>«Срок оплаты товара»</em> вместо <em>«Оплата»</em>).
                  </li>
                  <li>
                    <strong>Описание:</strong> сформулируйте границу допустимого — что именно нарушает закон или права поставщика (например: <em>«Срок оплаты превышает 7 рабочих дней с момента приёмки»</em> или <em>«Штраф за просрочку превышает 10% от цены договора»</em>).
                  </li>
                  <li>
                    <strong>Степень риска:</strong> задаёт верхнюю границу строгости замечания (критическое, внимание или низкий риск).
                  </li>
                </ul>
              </div>
            </details>

            <label className="form-label" htmlFor="rule-category">
              Категория <span aria-hidden="true">*</span>
            </label>
            {!customMode ? (
              <div className="category-select-row">
                <select
                  className="form-select category-select"
                  id="rule-category"
                  required
                  disabled={saving}
                  value={availableCategories.includes(draft.category) ? draft.category : availableCategories[0]}
                  onChange={event => {
                    if (event.target.value === '__custom__') {
                      setCustomMode(true);
                      setDraft({ ...draft, category: '' });
                    } else {
                      setDraft({ ...draft, category: event.target.value });
                    }
                  }}
                >
                  {availableCategories.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                  <option value="__custom__">+ Другая категория…</option>
                </select>
              </div>
            ) : (
              <div className="custom-category-row">
                <input
                  className="form-input"
                  id="rule-category"
                  autoFocus
                  required
                  disabled={saving}
                  maxLength={60}
                  placeholder="Введите название новой категории"
                  value={draft.category}
                  onChange={event => setDraft({ ...draft, category: event.target.value })}
                />
                <button
                  type="button"
                  className="secondary-button"
                  disabled={saving}
                  onClick={() => {
                    setCustomMode(false);
                    setDraft({ ...draft, category: availableCategories[0] });
                  }}
                >
                  Выбрать из списка
                </button>
              </div>
            )}

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

            <p className="form-hint">
              {rule
                ? 'Изменения сохранятся в базе и будут применимы к новым и повторным проверкам.'
                : 'Новое правило сохранится в базе и будет применяться при проверках.'}
            </p>
          </div>

          {/* Правая колонка: песочница интерактивной проверки правила */}
          <aside className="rule-editor-sandbox" aria-label="Песочница тестирования правила">
            <div className="sandbox-header">
              <h3>Проверить правило</h3>
              <p>Проверьте, какие фрагменты находит правило, до сохранения.</p>
            </div>

            <div className="sandbox-tabs" role="tablist">
              <button
                type="button"
                className={`sandbox-tab ${testSource === 'document' ? 'active' : ''}`}
                onClick={() => { setTestSource('document'); setTestError(null); }}
              >
                <FileText size={14} /> На документе
              </button>
              <button
                type="button"
                className={`sandbox-tab ${testSource === 'custom' ? 'active' : ''}`}
                onClick={() => { setTestSource('custom'); setTestError(null); }}
              >
                <FileSearch size={14} /> Вставить текст
              </button>
            </div>

            {testSource === 'document' ? (
              <div className="sandbox-input-group">
                <label className="form-label" htmlFor="sandbox-doc-select">
                  Документ для проверки
                </label>
                {documents.length > 0 ? (
                  <>
                    <select
                      id="sandbox-doc-select"
                      className="form-select sandbox-doc-select"
                      disabled={testing || saving}
                      value={selectedDocId}
                      onChange={e => {
                        setSelectedDocId(e.target.value);
                        setTestResult(null);
                        setTestError(null);
                      }}
                    >
                      {documents.map(doc => {
                        const isReady = doc.status === 'COMPLETED' || doc.phase === 'ready';
                        return (
                          <option key={doc.id} value={doc.id}>
                            {doc.projectTitle ? `${doc.projectTitle} / ` : ''}{doc.name} {isReady ? '✓' : `(обработка ${doc.progress}%)`}
                          </option>
                        );
                      })}
                    </select>
                    {!selectedDocReady && (
                      <div className="sandbox-warning-banner" role="status">
                        <AlertCircle size={16} />
                        <span>
                          Выбранный документ ещё обрабатывается ({selectedDocInfo?.progress || 0}%).
                          Дождитесь завершения анализа или выберите готовый документ.
                        </span>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="sandbox-warning-banner">
                    <AlertCircle size={16} />
                    <span>В проектах пока нет загруженных документов. Переключитесь на вкладку «Вставить текст» для быстрой проверки на фрагменте договора.</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="sandbox-input-group">
                <label className="form-label" htmlFor="sandbox-custom-snippet">
                  Фрагмент текста договора
                </label>
                <textarea
                  id="sandbox-custom-snippet"
                  className="form-input sandbox-textarea"
                  rows={3}
                  disabled={testing || saving}
                  placeholder="Вставьте сюда пункт договора, например: Оплата товара производится заказчиком в течение 45 календарных дней со дня подписания акта..."
                  value={customSnippet}
                  onChange={e => setCustomSnippet(e.target.value)}
                />
              </div>
            )}

            <button
              type="button"
              className="primary-button sandbox-run-button"
              disabled={testing || saving || !canTest}
              onClick={() => void runTest()}
            >
              {testing ? <LoaderCircle size={15} className="spin" /> : <Play size={14} />}
              {testing ? 'Проверяем правило…' : 'Проверить правило'}
            </button>

            {testError && <p className="field-error" role="alert">{testError}</p>}

            {/* Результаты проверки */}
            {testResult && (
              <div className="sandbox-results-panel">
                <div className={`sandbox-results-summary ${testResult.findings.length > 0 ? 'has-risk' : 'not-found'}`}>
                  <span>
                    {testResult.findings.length > 0
                      ? `Найдено замечаний: ${testResult.findings.length}`
                      : 'Замечаний не выявлено'}
                  </span>
                  {testResult.executionMs !== null && (
                    <span className="sandbox-execution-time">
                      {(testResult.executionMs / 1000).toFixed(1)} с
                    </span>
                  )}
                </div>

                {testResult.findings.length > 0 ? (
                  <div className="sandbox-findings-list">
                    {testResult.findings.map(finding => (
                      <article key={finding.id} className={`sandbox-finding-card ${finding.severity}`}>
                        <div className="sandbox-finding-top">
                          <span className={`severity-tag ${finding.severity}`}>
                            {riskLabels[finding.severity as RiskLevel] || severityLabels[finding.severity] || 'Замечание'}
                          </span>
                          <span className="sandbox-finding-clause">
                            {finding.clause ? `п. ${finding.clause}` : ''}
                            {finding.page ? ` · стр. ${finding.page}` : ''}
                          </span>
                        </div>
                        {finding.quote ? (
                          <blockquote className="sandbox-finding-quote">«{finding.quote}»</blockquote>
                        ) : null}
                        {finding.comment && (
                          <p className="sandbox-finding-comment">
                            <strong>Обоснование:</strong> {finding.comment}
                          </p>
                        )}
                        {finding.counterProposal && (
                          <p className="sandbox-finding-proposal">
                            <strong>Рекомендация:</strong> {finding.counterProposal}
                          </p>
                        )}
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="sandbox-empty-results">
                    <CheckCircle2 size={24} color="#16a34a" />
                    <h4>Замечаний по правилу не обнаружено</h4>
                    <p>Система не нашла кабальных или незаконных условий по заданной формулировке.</p>
                  </div>
                )}

                {/* Блок советов по уточнению формулировки */}
                {testResult.guidance && testResult.guidance.length > 0 && (
                  <div className={`sandbox-guidance-box ${testResult.findings.length > 0 ? 'neutral' : ''}`}>
                    <div className="sandbox-guidance-title">
                      <Lightbulb size={14} /> Подсказка по правилу
                    </div>
                    <ul className="sandbox-guidance-list">
                      {testResult.guidance.map((tip, i) => (
                        <li key={i}>{tip}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Спойлер отобранных фрагментов текста */}
                {testResult.fragments && testResult.fragments.length > 0 && (
                  <div>
                    <button
                      type="button"
                      className="sandbox-fragments-toggle"
                      onClick={() => setShowFragments(!showFragments)}
                    >
                      {showFragments ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      {showFragments
                        ? 'Скрыть найденные фрагменты'
                        : `Показать отобранные фрагменты (${testResult.fragments.length})`}
                    </button>
                    {showFragments && (
                      <div className="sandbox-fragments-list">
                        {testResult.fragments.map((fr, i) => (
                          <div key={i} className="sandbox-fragment-item">
                            <div className="sandbox-fragment-item-header">
                              <span>стр. {fr.page} {fr.clauseTitle ? `· ${fr.clauseTitle}` : ''}</span>
                              <span>релевантность: {Math.round(fr.score * 100)}%</span>
                            </div>
                            <div className="sandbox-fragment-item-content">{fr.content}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </aside>
        </div>

        {error && <p className="field-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" disabled={saving || testing} onClick={close}>
            Отмена
          </button>
          <button type="submit" className="primary-button" disabled={!valid || saving || testing}>
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
