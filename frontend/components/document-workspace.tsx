'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronsLeftRight, EllipsisVertical, Eye, FileCheck2, FileSearch, Hand, List, Maximize, Minimize, Minus, PanelLeftClose, PanelLeftOpen, Plus, RotateCcw, Search, ShieldCheck, X } from 'lucide-react';
import { documentInfo, getPageSections, outline, severityLabels, statusLabels } from '@/lib/mock-data';
import type { CheckRule, Finding, ReviewStatus, Severity } from '@/lib/types';
import { riskLabels } from '@/lib/rules';
import { HighlightedText, IconButton, Modal } from './ui';

type Props = { rules: CheckRule[]; onManageRules: () => void; onEditRule: (rule:CheckRule) => void; page: number; selected: number | null; search: string; findings: Finding[]; statuses: Record<number, ReviewStatus>; onPage: (page: number) => void; onSelect: (finding: Finding) => void; onStatus: (id: number, status: ReviewStatus) => void };

export function DocumentWorkspace({ rules, onManageRules, onEditRule, page, selected, search, findings, statuses, onPage, onSelect, onStatus }: Props) {
  const [zoom, setZoom] = useState(100);
  const [hand, setHand] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showPages, setShowPages] = useState(true);
  const [pageInput, setPageInput] = useState(String(page));
  const [tab, setTab] = useState<'findings' | 'navigation' | 'rules'>('findings');
  const [category, setCategory] = useState('all');
  const [severity, setSeverity] = useState('all');
  const [status, setStatus] = useState('all');
  const [filterText, setFilterText] = useState('');
  const [searchVisible, setSearchVisible] = useState(false);
  const [collapsed, setCollapsed] = useState<Severity[]>(['ok']);
  const [detail, setDetail] = useState<Finding | null>(null);
  const [mobilePane, setMobilePane] = useState<'document' | 'findings'>('document');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const scrollRef = useRef<HTMLDivElement>(null);
  const thumbnailRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<{x: number; y: number; left: number; top: number} | null>(null);
  const previousPage = useRef(page);
  const sections = useMemo(() => getPageSections(page), [page]);
  const categories = [...new Set(findings.map(f => f.category))];
  const filtered = useMemo(() => findings.filter(f => (category === 'all' || category === f.category) && (severity === 'all' || severity === f.severity) && (status === 'all' || (statuses[f.id] ?? 'unseen') === status) && `${f.title} ${f.description}`.toLocaleLowerCase('ru').includes(filterText.toLocaleLowerCase('ru'))).sort((a,b) => order === 'asc' ? a.id-b.id : b.id-a.id), [findings, category, severity, status, statuses, filterText, order]);
  const hasFilters = category !== 'all' || severity !== 'all' || status !== 'all' || filterText !== '';
  const reviewed = findings.filter(f => (statuses[f.id] ?? 'unseen') !== 'unseen').length;

  useEffect(() => {
    setPageInput(String(page));
    if (previousPage.current !== page) scrollRef.current?.scrollTo({ top: 0, left: 0 });
    previousPage.current = page;
    thumbnailRef.current?.scrollIntoView({ block: 'center', inline: 'nearest' });
    if (selected) {
      const element = scrollRef.current?.querySelector(`[data-finding="${selected}"]`);
      element?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [page, selected]);
  function commitPage() { const value = Number(pageInput); if (Number.isFinite(value) && value >= 1) onPage(Math.min(54, value)); else setPageInput(String(page)); }
  function select(f: Finding) { onSelect(f); setMobilePane('document'); }
  function resetFilters() { setCategory('all'); setStatus('all'); setSeverity('all'); setFilterText(''); }

  return <div className={`document-workspace ${expanded ? 'reader-expanded' : ''} ${showPages ? '' : 'pages-hidden'} mobile-${mobilePane}`}>
    <div className="mobile-pane-tabs"><button className={mobilePane === 'document' ? 'active' : ''} onClick={() => setMobilePane('document')}><FileSearch size={16} />Документ</button><button className={mobilePane === 'findings' ? 'active' : ''} onClick={() => { setMobilePane('findings'); setExpanded(false); }}><List size={16} />Замечания <span>{findings.filter(f => f.severity !== 'ok').length}</span></button></div>
    {showPages && <aside className="pages-sidebar" aria-label="Страницы документа"><div className="panel-title"><span>Страницы</span><IconButton label="Скрыть страницы" onClick={() => setShowPages(false)}><PanelLeftClose size={16} /></IconButton></div><div className="thumbnails">{Array.from({length:54}, (_, index) => index + 1).map(p => <button ref={p === page ? thumbnailRef : undefined} key={p} aria-label={`Страница ${p}`} aria-current={p === page ? 'page' : undefined} className={`thumbnail ${p === page ? 'selected' : ''}`} onClick={() => onPage(p)}><span className="mini-paper" aria-hidden="true"><b /><span className="mini-paragraph">{Array.from({length:8}, (_, i) => <i key={i} style={{width:`${i === 7 ? 63 : 90 + (i % 3) * 5}%`}} />)}</span>{findings.some(f => f.page === p && f.severity === 'critical') && <span className="mini-highlight" />}<b /><span className="mini-paragraph">{Array.from({length:7}, (_, i) => <i key={i} style={{width:`${i === 6 ? 54 : 100 - i % 2 * 7}%`}} />)}</span><b /><span className="mini-paragraph short">{Array.from({length:5}, (_, i) => <i key={i} />)}</span></span><span className="thumbnail-label">{p}{findings.some(f => f.page === p && f.severity !== 'ok') && <i />}</span></button>)}</div></aside>}
    <section className="reader" aria-label="Просмотр документа"><div className="reader-toolbar">
      {!showPages && <IconButton label="Показать страницы" onClick={() => setShowPages(true)}><PanelLeftOpen size={17} /></IconButton>}
      <div className="page-control"><IconButton label="Предыдущая страница" onClick={() => onPage(page - 1)} disabled={page === 1}><ChevronLeft size={17} /></IconButton><input type="number" aria-label="Номер страницы" min={1} max={54} value={pageInput} onChange={e => setPageInput(e.target.value)} onBlur={commitPage} onKeyDown={e => { if (e.key === 'Enter') { commitPage(); e.currentTarget.blur(); } }} /><span>/ 54</span><IconButton label="Следующая страница" onClick={() => onPage(page + 1)} disabled={page === 54}><ChevronRight size={17} /></IconButton></div>
      <div className="toolbar-divider" />
      <div className="zoom-control"><IconButton label="Уменьшить масштаб" onClick={() => setZoom(Math.max(50, zoom - 10))} disabled={zoom === 50}><Minus size={16} /></IconButton><button title="Сбросить масштаб" onClick={() => setZoom(100)}>{zoom}%</button><IconButton label="Увеличить масштаб" onClick={() => setZoom(Math.min(160, zoom + 10))} disabled={zoom === 160}><Plus size={16} /></IconButton></div>
      <div className="toolbar-divider" /><IconButton label="Перемещать документ" active={hand} aria-pressed={hand} onClick={() => setHand(!hand)}><Hand size={17} /></IconButton><IconButton label="По ширине страницы" onClick={() => { setZoom(100); scrollRef.current?.scrollTo({left:0}); }}><ChevronsLeftRight size={18} /></IconButton>
      <div className="toolbar-spacer" /><IconButton label={expanded ? 'Свернуть документ' : 'Развернуть документ'} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize size={17} /> : <Maximize size={17} />}</IconButton>
    </div>
    <div ref={scrollRef} className={`paper-scroll ${hand ? 'hand-mode' : ''}`} onPointerDown={e => { if (!hand || (e.target as HTMLElement).closest('button')) return; const el = e.currentTarget; drag.current = {x:e.clientX, y:e.clientY, left:el.scrollLeft, top:el.scrollTop}; el.setPointerCapture(e.pointerId); }} onPointerMove={e => { if (drag.current) { e.currentTarget.scrollLeft = drag.current.left - e.clientX + drag.current.x; e.currentTarget.scrollTop = drag.current.top - e.clientY + drag.current.y; } }} onPointerUp={() => {drag.current = null;}} onPointerCancel={() => {drag.current = null;}}>
      <article className="document-paper" style={{width: `${zoom}%`, minWidth: `${zoom}%`, fontSize: `${zoom * .145}px`}} aria-label={`Текст страницы ${page}`}><div className="paper-running-header"><span>ПРОЕКТ КОНТРАКТА</span><span>№ 24/2026</span></div>
        {sections.map(section => <section className="contract-section" key={section.title}><h2>{section.title}</h2>{section.paragraphs.map(paragraph => {
          const finding = findings.find(f => f.id === paragraph.findingId);
          const annotated = finding && finding.severity !== 'ok';
          return <div key={paragraph.clause} data-finding={finding?.id} className={`contract-paragraph ${annotated ? `annotation ${finding.severity}` : ''} ${selected === finding?.id ? 'focused' : ''}`}>
            {annotated && <button className="annotation-marker" aria-label={`Замечание ${finding.id}: ${finding.title}`} onClick={() => { onSelect(finding); setDetail(finding); }}>{finding.id}</button>}
            <span className="clause-number">{paragraph.clause}.</span><p><HighlightedText text={paragraph.text} query={search} /></p>
          </div>;
        })}</section>)}
        <div className="paper-signatures"><span>Заказчик ____________</span><span>Поставщик ____________</span></div><div className="paper-page-number">{page}</div>
      </article>
    </div><div className="reader-footer"><span>Страница {page} из 54</span><span>Текстовая версия <span className="subtle-dot">·</span> PDF</span></div></section>

    {!expanded && <aside className="review-panel" aria-label="Проверка документа"><div className="review-tabs" role="tablist" aria-label="Раздел проверки">{([{id:'findings',label:'Замечания'},{id:'navigation',label:'Навигация'},{id:'rules',label:'Правила проверки'}] as const).map(t => <button role="tab" id={`tab-${t.id}`} aria-controls={`panel-${t.id}`} aria-selected={tab === t.id} key={t.id} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}>{t.label}{t.id === 'findings' && <span>{findings.filter(f => f.severity !== 'ok').length}</span>}</button>)}</div>
      {tab === 'findings' && <div role="tabpanel" id="panel-findings" aria-labelledby="tab-findings" className="findings-pane"><div className="filters"><label><span className="sr-only">Категория</span><select value={category} onChange={e => setCategory(e.target.value)}><option value="all">Все категории</option>{categories.map(c => <option key={c}>{c}</option>)}</select><ChevronDown size={14} /></label><label><span className="sr-only">Статус проверки</span><select value={status} onChange={e => setStatus(e.target.value)}><option value="all">Все статусы</option>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={14} /></label><label><span className="sr-only">Уровень риска</span><select value={severity} onChange={e => setSeverity(e.target.value)}><option value="all">Все уровни</option><option value="critical">Критические</option><option value="warning">Внимание</option><option value="low">Низкий риск</option><option value="ok">Без замечаний</option></select><ChevronDown size={14} /></label><IconButton label="Поиск замечаний" active={searchVisible} onClick={() => setSearchVisible(!searchVisible)}><Search size={18} /></IconButton></div>
      {searchVisible && <div className="finding-search field-search"><Search size={16} /><input autoFocus placeholder="Название или текст замечания" aria-label="Поиск замечаний" value={filterText} onChange={e => setFilterText(e.target.value)} /><IconButton label="Очистить поиск замечаний" onClick={() => setFilterText('')}><X size={15} /></IconButton></div>}
      {hasFilters && <div className="filter-summary"><span>Найдено: {filtered.length}</span><button onClick={resetFilters}><RotateCcw size={13} />Сбросить фильтры</button></div>}
      <div className="findings-scroll"><table className="findings-table"><colgroup><col className="col-number" /><col className="col-severity" /><col /><col className="col-clause" /><col className="col-page" /><col className="col-status" /><col className="col-more" /></colgroup><thead><tr><th><button aria-label="Изменить порядок замечаний" onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}>№ <span>{order === 'asc' ? '↕' : '↓'}</span></button></th><th className="severity-header">Риск</th><th>Замечание</th><th>Пункт</th><th>Стр.</th><th>Статус проверки</th><th aria-label="Действия" /></tr></thead>
        {(['critical','warning','low','ok'] as const).map(level => {
          const group = filtered.filter(f => f.severity === level);
          if (!group.length) return null;
          const isCollapsed = collapsed.includes(level);
          return <tbody key={level}><tr className="group-row"><th colSpan={7}><button onClick={() => setCollapsed(previous => previous.includes(level) ? previous.filter(item => item !== level) : [...previous,level])} aria-expanded={!isCollapsed}><span className={`group-bar ${level}`} /><span>{severityLabels[level]} <em>({group.length})</em></span><ChevronDown size={16} className={isCollapsed ? 'rotated' : ''} /></button></th></tr>{!isCollapsed && group.map(f => <tr key={f.id} data-selected={selected === f.id} className={`finding-row ${selected === f.id ? 'selected-row' : ''}`}><td className="number-cell">{f.id}</td><td className="severity-cell"><span className={`risk-dot ${f.severity}`} title={severityLabels[f.severity]} /><span className="sr-only">{severityLabels[f.severity]}</span></td><td className="finding-cell"><button onClick={() => select(f)} className="finding-link"><strong>{f.title}</strong><span>{f.description}</span></button></td><td className="clause-cell"><button onClick={() => select(f)}>п. {f.clause}</button></td><td className="page-cell"><button onClick={() => select(f)}>{f.page}</button></td><td className="status-cell"><div className={`review-status ${statuses[f.id] ?? 'unseen'}`}><span>{statuses[f.id] === 'accepted' ? <Check size={10} /> : statuses[f.id] === 'dismissed' ? <X size={10} /> : null}</span><select aria-label={`Статус замечания ${f.id}`} value={statuses[f.id] ?? 'unseen'} onChange={e => onStatus(f.id, e.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></div></td><td className="more-cell"><IconButton label={`Подробнее о замечании ${f.id}`} onClick={() => setDetail(f)}><EllipsisVertical size={16} /></IconButton></td></tr>)}</tbody>;
        })}</table>
        {!filtered.length && <div className="empty-state"><FileSearch size={30} /><h3>Замечаний не найдено</h3><p>Попробуйте изменить условия фильтра.</p>{hasFilters && <button className="secondary-button" onClick={resetFilters}>Сбросить фильтры</button>}</div>}
      </div><div className="review-footer"><span><Eye size={14} />Просмотрено {reviewed} из {findings.length}</span><div className="review-progress" role="progressbar" aria-label="Просмотренные правила" aria-valuemin={0} aria-valuemax={findings.length || 1} aria-valuenow={reviewed}><i style={{width:`${findings.length ? reviewed / findings.length * 100 : 0}%`}} /></div></div></div>}
      {tab === 'navigation' && <div className="outline-pane" role="tabpanel" id="panel-navigation" aria-labelledby="tab-navigation"><div className="pane-heading"><List size={18} /><span>Содержание документа</span></div>{outline.map(section => <button className={page === section.page ? 'current' : ''} key={section.title} onClick={() => { onPage(section.page); setMobilePane('document'); }}><span>{section.title}</span><span className="outline-page">{section.page}<ChevronRight size={15} /></span></button>)}</div>}
      {tab === 'rules' && <div className="inline-rules" role="tabpanel" id="panel-rules" aria-labelledby="tab-rules"><div className="pane-heading"><ShieldCheck size={18} /><span>Правила проверки · {rules.length}</span></div><div className="manage-rules-link"><button className="secondary-button" onClick={onManageRules}>Управление правилами</button></div>{rules.map(rule => <button key={rule.id} onClick={() => onEditRule(rule)} aria-label={`Редактировать правило «${rule.title}»`}><span className={`rule-check ${rule.severity}`}><FileCheck2 size={18} /></span><span><strong>{rule.title}</strong><small>{riskLabels[rule.severity]} · {!rule.enabled ? 'Выключено' : findings.some(f=>f.id===rule.id) ? 'Есть результат проверки' : 'Ещё не проверено'}</small></span><ChevronRight size={16} /></button>)}{!rules.length && <div className="empty-state"><p>Добавьте правила в разделе «Правила».</p></div>}</div>}
    </aside>}

    {detail && <Modal title={`Замечание № ${detail.id}`} onClose={() => setDetail(null)}><div className="finding-detail"><span className={`severity-tag ${detail.severity}`}>{severityLabels[detail.severity]}</span><h3>{detail.title}</h3><p>{detail.description}</p><div className="detail-meta"><span>Пункт {detail.clause}</span><span>Страница {detail.page}</span><span>{detail.category}</span></div><h4>Фрагмент документа</h4><blockquote>{detail.quote}</blockquote><h4>На что обратить внимание</h4><p>{detail.recommendation}</p><label className="form-label" htmlFor="detail-status">Статус проверки</label><select id="detail-status" className="form-select" value={statuses[detail.id] ?? 'unseen'} onChange={e => onStatus(detail.id, e.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><small className="detail-disclaimer">Пример результата проверки. Автоматический анализ не выполнялся.</small></div><div className="modal-actions"><button className="secondary-button" onClick={() => setDetail(null)}>Закрыть</button><button className="primary-button" onClick={() => { select(detail); setDetail(null); }}>К фрагменту</button></div></Modal>}
  </div>;
}
