'use client';

import { useState } from 'react';
import { AlertTriangle, BookOpenCheck, Pencil, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react';
import type { CheckRule, RuleDraft, RiskLevel } from '@/lib/types';
import { riskLabels } from '@/lib/rules';
import { IconButton, Modal } from './ui';

type Props = { rules: CheckRule[]; onAdd: () => void; onEdit: (rule: CheckRule) => void; onDelete: (rule: CheckRule) => void; onToggle: (rule: CheckRule) => void };
export function RulesManager({rules, onAdd, onEdit, onDelete, onToggle}: Props) {
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState('all');
  const filtered = rules.filter(rule => `${rule.title} ${rule.description} ${rule.category}`.toLocaleLowerCase('ru').includes(query.trim().toLocaleLowerCase('ru')) && (level === 'all' || rule.severity === level));
  return <section className="secondary-view rules-view">
    <div className="view-title"><div><span className="eyebrow">НАСТРОЙКА ПРОВЕРКИ</span><h1>Правила проверки</h1><p>Создавайте свои правила и определяйте степень риска.</p></div><button className="primary-button" onClick={onAdd}><Plus size={18} />Добавить правило</button></div>
    <div className="rules-toolbar"><label className="field-search"><Search size={18} /><input placeholder="Найти правило..." aria-label="Найти правило" value={query} onChange={e => setQuery(e.target.value)} /></label><select className="form-select rule-risk-filter" aria-label="Фильтр правил по риску" value={level} onChange={e => setLevel(e.target.value)}><option value="all">Все степени риска</option>{Object.entries(riskLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><span className="count-chip"><ShieldCheck size={16} />{rules.filter(rule => rule.enabled).length} из {rules.length} включено</span></div>
    <div className="rules-grid">{filtered.map(rule => <article key={rule.id} className={`rule-card ${!rule.enabled ? 'rule-disabled' : ''}`}><div className="rule-card-top"><span className={`severity-tag ${rule.severity}`}>{riskLabels[rule.severity]}</span><button role="switch" aria-checked={rule.enabled} aria-label={`Правило: ${rule.title}`} className="switch" onClick={() => onToggle(rule)}><span /></button></div><h3>{rule.title}</h3><p>{rule.description || 'Описание не добавлено.'}</p><div className="rule-card-footer"><small>{rule.category}</small><div><IconButton label={`Редактировать правило «${rule.title}»`} onClick={() => onEdit(rule)}><Pencil size={16} /></IconButton><IconButton className="delete-rule-button" label={`Удалить правило «${rule.title}»`} onClick={() => onDelete(rule)}><Trash2 size={16} /></IconButton></div></div></article>)}</div>
    {!filtered.length && <div className="empty-state"><BookOpenCheck size={32} /><h3>{rules.length ? 'Правила не найдены' : 'Пока нет правил'}</h3><p>{rules.length ? 'Измените запрос или степень риска.' : 'Добавьте первое правило для проверки документов.'}</p>{!rules.length && <button className="primary-button" onClick={onAdd}><Plus size={16} />Добавить правило</button>}</div>}
  </section>;
}

export function RuleEditor({rule, categories, onSave, onClose}: {rule: CheckRule | null; categories: string[]; onSave: (draft: RuleDraft) => void; onClose: () => void}) {
  const [draft, setDraft] = useState<RuleDraft>(rule ? {title:rule.title, description:rule.description, category:rule.category, severity:rule.severity, enabled:rule.enabled} : {title:'',description:'',category:'Общие условия',severity:'warning',enabled:true});
  return <Modal title={rule ? 'Редактировать правило' : 'Добавить правило'} onClose={onClose}>
    <form onSubmit={event => {event.preventDefault(); if (!draft.title.trim() || !draft.category.trim()) return; onSave({...draft,title:draft.title.trim(),description:draft.description.trim(),category:draft.category.trim()});}}>
      <label className="form-label" htmlFor="rule-title">Название правила <span aria-hidden="true">*</span></label><input className="form-input" id="rule-title" autoFocus required maxLength={120} placeholder="Например, срок оплаты" value={draft.title} onChange={e => setDraft({...draft,title:e.target.value})} />
      <label className="form-label" htmlFor="rule-description">Описание</label><textarea className="form-input" id="rule-description" rows={3} maxLength={1000} placeholder="Что необходимо проверить в документе" value={draft.description} onChange={e => setDraft({...draft,description:e.target.value})} />
      <label className="form-label" htmlFor="rule-category">Категория <span aria-hidden="true">*</span></label><input className="form-input" id="rule-category" list="rule-categories" required maxLength={60} value={draft.category} onChange={e => setDraft({...draft,category:e.target.value})} /><datalist id="rule-categories">{categories.map(category => <option key={category} value={category} />)}</datalist>
      <fieldset className="risk-choices"><legend className="form-label">Степень риска</legend>{Object.entries(riskLabels).map(([value,label]) => <label key={value} className={`risk-choice ${value} ${draft.severity === value ? 'selected' : ''}`}><input type="radio" name="rule-risk" value={value} checked={draft.severity === value} onChange={() => setDraft({...draft,severity:value as RiskLevel})} /><span className={`risk-dot ${value}`} />{label}</label>)}</fieldset>
      <label className="rule-enable-field"><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({...draft,enabled:e.target.checked})} />Использовать правило при проверке</label>
      {!rule && <p className="form-hint">Новое правило появится в списке. Результаты проверки для него пока отсутствуют.</p>}
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Отмена</button><button className="primary-button" disabled={!draft.title.trim() || !draft.category.trim()}>{rule ? 'Сохранить изменения' : 'Добавить правило'}</button></div>
    </form>
  </Modal>;
}

export function DeleteRuleDialog({rule,onConfirm,onClose}: {rule:CheckRule;onConfirm:()=>void;onClose:()=>void}) {
  return <Modal title="Точно удалить?" onClose={onClose}><div className="delete-rule-intro"><span><AlertTriangle size={24} /></span><p>Правило <strong>«{rule.title}»</strong> будет удалено из списка. Связанные замечания перестанут отображаться в документе.</p></div><div className="modal-actions"><button autoFocus className="secondary-button" onClick={onClose}>Отмена</button><button className="primary-button" onClick={onConfirm}><Trash2 size={16} />Удалить правило</button></div></Modal>;
}
