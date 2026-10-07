'use client';

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronsLeftRight, EllipsisVertical, Eye, FileCheck2, FileSearch, Hand, List, Maximize, Minimize, Minus, PanelLeftClose, PanelLeftOpen, Plus, RotateCcw, Search, ShieldCheck, X } from 'lucide-react';
import { documentInfo, getPageSections, outline, severityLabels, statusLabels } from '@/lib/mock-data';
import type { CheckRule, Finding, ReviewStatus, Severity } from '@/lib/types';
import { riskLabels } from '@/lib/rules';
import { HighlightedText, IconButton, Modal } from './ui';
import './review-enhancements.css';

const reviewTabs = [
  { id: 'findings', label: 'Замечания' },
  { id: 'navigation', label: 'Навигация' },
  { id: 'rules', label: 'Правила проверки' },
] as const;
type ReviewTab = typeof reviewTabs[number]['id'];

type Props = { rules: CheckRule[]; onManageRules: () => void; onEditRule: (rule:CheckRule) => void; page: number; selected: number | null; search: string; findings: Finding[]; statuses: Record<number, ReviewStatus>; onPage: (page: number) => void; onSelect: (finding: Finding) => void; onStatus: (id: number, status: ReviewStatus) => void };

export function DocumentWorkspace({ rules, onManageRules, onEditRule, page, selected, search, findings, statuses, onPage, onSelect, onStatus }: Props) {
  const [zoom, setZoom] = useState(100);
  const [hand, setHand] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showPages, setShowPages] = useState(true);
  const [pageInput, setPageInput] = useState(String(page));
  const [tab, setTab] = useState<ReviewTab>('findings');
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
  const searchToggleRef = useRef<HTMLButtonElement>(null);
  const tabRefs = useRef<Partial<Record<ReviewTab, HTMLButtonElement | null>>>({});
  const thumbnailRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<{x: number; y: number; left: number; top: number} | null>(null);
  const previousPage = useRef(page);
  const sections = useMemo(() => getPageSections(page), [page]);
  const categories = [...new Set(findings.map(f => f.category))];
  const filtered = useMemo(() => findings.filter(f => (category === 'all' || category === f.category) && (severity === 'all' || severity === f.severity) && (status === 'all' || (statuses[f.id] ?? 'unseen') === status) && `${f.title} ${f.description}`.toLocaleLowerCase('ru').includes(filterText.trim().toLocaleLowerCase('ru'))).sort((a,b) => order === 'asc' ? a.id-b.id : b.id-a.id), [findings, category, severity, status, statuses, filterText, order]);
  const activeFilterCount = [category !== 'all', severity !== 'all', status !== 'all', Boolean(filterText.trim())].filter(Boolean).length;
  const hasFilters = activeFilterCount > 0;
  const selectedFinding = findings.find(f => f.id === selected);
  const riskCount = findings.filter(f => f.severity !== 'ok').length;
  const reviewed = findings.filter(f => (statuses[f.id] ?? 'unseen') !== 'unseen').length;
  const reviewPercent = findings.length ? Math.round(reviewed / findings.length * 100) : 0;

  useEffect(() => {
    setPageInput(String(page));
    if (previousPage.current !== page) scrollRef.current?.scrollTo({ top: 0, left: 0 });
    previousPage.current = page;
    const thumbnail = thumbnailRef.current;
    const thumbnails = thumbnail?.parentElement;
    if (thumbnail && thumbnails) {
      const top = thumbnails.scrollTop + thumbnail.getBoundingClientRect().top - thumbnails.getBoundingClientRect().top;
      thumbnails.scrollTo({ top: top - (thumbnails.clientHeight - thumbnail.clientHeight) / 2 });
    }
    if (selected !== null) {
      const element = scrollRef.current?.querySelector(`[data-finding="${selected}"]`);
      const viewport = scrollRef.current;
      if (element && viewport) {
        const target = element.getBoundingClientRect();
        const bounds = viewport.getBoundingClientRect();
        if (target.top < bounds.top || target.bottom > bounds.bottom) {
          viewport.scrollTo({ top: viewport.scrollTop + target.top - bounds.top - 16, behavior: 'smooth' });
        }
      }
    }
  }, [page, selected]);
  useEffect(() => {
    if (selectedFinding) setCollapsed(previous => previous.filter(level => level !== selectedFinding.severity));
  }, [selectedFinding]);

  function commitPage() {
    const value = Number(pageInput);
    if (!pageInput.trim() || !Number.isFinite(value)) { setPageInput(String(page)); return; }
    const nextPage = Math.max(1, Math.min(documentInfo.pages, Math.trunc(value)));
    setPageInput(String(nextPage));
    if (nextPage !== page) onPage(nextPage);
  }
  function closeSearch() {
    setFilterText('');
    setSearchVisible(false);
    searchToggleRef.current?.focus();
  }
  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, current: ReviewTab) {
    const index = reviewTabs.findIndex(item => item.id === current);
    let nextIndex: number;
    switch (event.key) {
      case 'ArrowRight': nextIndex = (index + 1) % reviewTabs.length; break;
      case 'ArrowLeft': nextIndex = (index - 1 + reviewTabs.length) % reviewTabs.length; break;
      case 'Home': nextIndex = 0; break;
      case 'End': nextIndex = reviewTabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    const nextTab = reviewTabs[nextIndex].id;
    setTab(nextTab);
    tabRefs.current[nextTab]?.focus();
  }
  function select(f: Finding) { onSelect(f); setMobilePane('document'); }
  function resetFilters() { setCategory('all'); setStatus('all'); setSeverity('all'); setFilterText(''); }

  return <div className={`document-workspace ${expanded ? 'reader-expanded' : ''} ${showPages ? '' : 'pages-hidden'} mobile-${mobilePane}`}>
    <div className="mobile-pane-tabs" role="group" aria-label="Панель документа"><button aria-pressed={mobilePane === 'document'} className={mobilePane === 'document' ? 'active' : ''} onClick={() => setMobilePane('document')}><FileSearch size={16} />Документ</button><button aria-pressed={mobilePane === 'findings'} className={mobilePane === 'findings' ? 'active' : ''} onClick={() => { setMobilePane('findings'); setExpanded(false); }}><List size={16} />Замечания <span>{riskCount}</span></button></div>
    {showPages && <aside className="pages-sidebar" aria-label="Страницы документа"><div className="panel-title"><span>Страницы</span><IconButton label="Скрыть страницы" onClick={() => setShowPages(false)}><PanelLeftClose size={16} /></IconButton></div><div className="thumbnails">{Array.from({length:documentInfo.pages}, (_, index) => index + 1).map(p => <button ref={p === page ? thumbnailRef : undefined} key={p} aria-label={`Страница ${p}`} aria-current={p === page ? 'page' : undefined} className={`thumbnail ${p === page ? 'selected' : ''}`} onClick={() => onPage(p)}><span className="mini-paper" aria-hidden="true"><b /><span className="mini-paragraph">{Array.from({length:8}, (_, i) => <i key={i} style={{width:`${i === 7 ? 63 : 90 + (i % 3) * 5}%`}} />)}</span>{findings.some(f => f.page === p && f.severity === 'critical') && <span className="mini-highlight" />}<b /><span className="mini-paragraph">{Array.from({length:7}, (_, i) => <i key={i} style={{width:`${i === 6 ? 54 : 100 - i % 2 * 7}%`}} />)}</span><b /><span className="mini-paragraph short">{Array.from({length:5}, (_, i) => <i key={i} />)}</span></span><span className="thumbnail-label">{p}{findings.some(f => f.page === p && f.severity !== 'ok') && <i />}</span></button>)}</div></aside>}
    <section className="reader" aria-label="Просмотр документа"><div className="reader-toolbar">
      {!showPages && <IconButton label="Показать страницы" onClick={() => setShowPages(true)}><PanelLeftOpen size={17} /></IconButton>}
      <div className="page-control"><IconButton label="Предыдущая страница" onClick={() => onPage(page - 1)} disabled={page === 1}><ChevronLeft size={17} /></IconButton><input type="number" aria-label="Номер страницы" min={1} max={documentInfo.pages} step={1} value={pageInput} onChange={e => setPageInput(e.target.value)} onBlur={commitPage} onKeyDown={e => { if (e.key === 'Enter') { e.currentTarget.blur(); } }} /><span>/ {documentInfo.pages}</span><IconButton label="Следующая страница" onClick={() => onPage(page + 1)} disabled={page === documentInfo.pages}><ChevronRight size={17} /></IconButton></div>
      <div className="toolbar-divider" />
      <div className="zoom-control"><IconButton label="Уменьшить масштаб" onClick={() => setZoom(Math.max(50, zoom - 10))} disabled={zoom === 50}><Minus size={16} /></IconButton><button title="Сбросить масштаб" onClick={() => setZoom(100)}>{zoom}%</button><IconButton label="Увеличить масштаб" onClick={() => setZoom(Math.min(160, zoom + 10))} disabled={zoom === 160}><Plus size={16} /></IconButton></div>
      <div className="toolbar-divider" /><IconButton label="Перемещать документ" active={hand} aria-pressed={hand} onClick={() => setHand(!hand)}><Hand size={17} /></IconButton><IconButton label="По ширине страницы" onClick={() => { setZoom(100); scrollRef.current?.scrollTo({left:0}); }}><ChevronsLeftRight size={18} /></IconButton>
      <div className="toolbar-spacer" /><IconButton label={expanded ? 'Свернуть документ' : 'Развернуть документ'} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize size={17} /> : <Maximize size={17} />}</IconButton>
    </div>
    {selectedFinding && <div className={`selected-finding-context ${selectedFinding.severity}`}>
      <span className={`risk-dot ${selectedFinding.severity}`} aria-hidden="true" />
      <button className="selected-finding-title" onClick={() => setDetail(selectedFinding)} title={selectedFinding.title}>
        <span>Замечание № {selectedFinding.id} · п. {selectedFinding.clause}</span><strong>{selectedFinding.title}</strong>
      </button>
      <button className="return-to-findings" onClick={() => { setMobilePane('findings'); setExpanded(false); setTab('findings'); }} aria-label="Вернуться к замечаниям"><List size={16} /></button>
      <IconButton label="Подробнее о выбранном замечании" onClick={() => setDetail(selectedFinding)}><ChevronRight size={16} /></IconButton>
    </div>}
    <div ref={scrollRef} className={`paper-scroll ${hand ? 'hand-mode' : ''}`} onPointerDown={e => { if (!hand || (e.target as HTMLElement).closest('button')) return; const el = e.currentTarget; drag.current = {x:e.clientX, y:e.clientY, left:el.scrollLeft, top:el.scrollTop}; el.setPointerCapture(e.pointerId); }} onPointerMove={e => { if (drag.current) { e.currentTarget.scrollLeft = drag.current.left - e.clientX + drag.current.x; e.currentTarget.scrollTop = drag.current.top - e.clientY + drag.current.y; } }} onPointerUp={() => {drag.current = null;}} onPointerCancel={() => {drag.current = null;}} onLostPointerCapture={() => {drag.current = null;}}>
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
    </div><div className="reader-footer"><span>Страница {page} из {documentInfo.pages}</span><span>Текстовая версия <span className="subtle-dot">·</span> PDF</span></div></section>

    {!expanded && <aside className="review-panel" aria-label="Проверка документа"><div className="review-tabs" role="tablist" aria-label="Раздел проверки">{reviewTabs.map(t => <button ref={element => { tabRefs.current[t.id] = element; }} tabIndex={tab === t.id ? 0 : -1} onKeyDown={event => navigateTabs(event, t.id)} role="tab" id={`tab-${t.id}`} aria-controls={tab === t.id ? `panel-${t.id}` : undefined} aria-selected={tab === t.id} key={t.id} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}>{t.label}{t.id === 'findings' && <span>{riskCount}</span>}</button>)}</div>
      {tab === 'findings' && <div role="tabpanel" tabIndex={0} id="panel-findings" aria-labelledby="tab-findings" className="findings-pane"><div className="filters"><label><span className="sr-only">Категория</span><select value={category} onChange={e => setCategory(e.target.value)}><option value="all">Все категории</option>{categories.map(c => <option key={c}>{c}</option>)}</select><ChevronDown size={14} /></label><label><span className="sr-only">Статус проверки</span><select value={status} onChange={e => setStatus(e.target.value)}><option value="all">Все статусы</option>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={14} /></label><label><span className="sr-only">Уровень риска</span><select value={severity} onChange={e => setSeverity(e.target.value)}><option value="all">Все уровни</option><option value="critical">Критические</option><option value="warning">Внимание</option><option value="low">Низкий риск</option><option value="ok">Без замечаний</option></select><ChevronDown size={14} /></label><button type="button" ref={searchToggleRef} className={`icon-button ${searchVisible ? 'is-active' : ''}`} aria-label={searchVisible ? 'Закрыть поиск замечаний' : 'Поиск замечаний'} title={searchVisible ? 'Закрыть поиск замечаний' : 'Поиск замечаний'} aria-expanded={searchVisible} aria-controls={searchVisible ? 'finding-search' : undefined} onClick={() => searchVisible ? closeSearch() : setSearchVisible(true)}><Search size={18} /></button></div>
      {searchVisible && <div id="finding-search" className="finding-search field-search" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); closeSearch(); } }}><Search size={16} /><input autoFocus placeholder="Название или текст замечания" aria-label="Поиск замечаний" value={filterText} onChange={e => setFilterText(e.target.value)} /><IconButton label="Очистить поиск замечаний" disabled={!filterText} onClick={() => setFilterText('')}><X size={15} /></IconButton></div>}
      <div className="filter-summary"><span role="status" aria-live="polite">Результаты: <strong>{filtered.length}</strong> из {findings.length}</span>{hasFilters ? <button onClick={resetFilters}><RotateCcw size={13} />Сбросить фильтры <span className="filter-count">{activeFilterCount}</span></button> : <span className="filter-summary-note">По уровню риска</span>}</div>
      <div className="findings-scroll"><table className="findings-table"><colgroup><col className="col-number" /><col className="col-severity" /><col /><col className="col-clause" /><col className="col-page" /><col className="col-status" /><col className="col-more" /></colgroup><thead><tr><th aria-sort={order === 'asc' ? 'ascending' : 'descending'}><button aria-label={`Номера внутри групп: ${order === 'asc' ? 'по возрастанию' : 'по убыванию'}. Изменить порядок`} onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}>№ <span>{order === 'asc' ? '↑' : '↓'}</span></button></th><th className="severity-header">Риск</th><th>Замечание</th><th>Пункт</th><th>Стр.</th><th>Статус проверки</th><th aria-label="Действия" /></tr></thead>
        {(['critical','warning','low','ok'] as const).map(level => {
          const group = filtered.filter(f => f.severity === level);
          if (!group.length) return null;
          const isCollapsed = collapsed.includes(level);
          return <tbody key={level}><tr className="group-row"><th colSpan={7}><button onClick={() => setCollapsed(previous => previous.includes(level) ? previous.filter(item => item !== level) : [...previous,level])} aria-expanded={!isCollapsed}><span className={`group-bar ${level}`} /><span>{severityLabels[level]} <em>({group.length})</em></span><ChevronDown size={16} className={isCollapsed ? 'rotated' : ''} /></button></th></tr>{!isCollapsed && group.map(f => <tr key={f.id} data-selected={selected === f.id} className={`finding-row ${selected === f.id ? 'selected-row' : ''}`}><td className="number-cell">{f.id}</td><td className="severity-cell"><span className={`risk-dot ${f.severity}`} title={severityLabels[f.severity]} /><span className="sr-only">{severityLabels[f.severity]}</span></td><td className="finding-cell"><button onClick={() => select(f)} className="finding-link" aria-current={selected === f.id ? 'true' : undefined}><strong><HighlightedText text={f.title} query={filterText} /></strong><span><HighlightedText text={f.description} query={filterText} /></span><small className="finding-mobile-meta">п. {f.clause} · стр. {f.page}</small></button></td><td className="clause-cell"><button onClick={() => select(f)}>п. {f.clause}</button></td><td className="page-cell"><button onClick={() => select(f)}>{f.page}</button></td><td className="status-cell"><div className={`review-status ${statuses[f.id] ?? 'unseen'}`}><span>{statuses[f.id] === 'accepted' ? <Check size={10} /> : statuses[f.id] === 'dismissed' ? <X size={10} /> : null}</span><select aria-label={`Статус замечания ${f.id}`} value={statuses[f.id] ?? 'unseen'} onChange={e => onStatus(f.id, e.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={12} aria-hidden="true" /></div></td><td className="more-cell"><IconButton label={`Подробнее о замечании ${f.id}`} onClick={() => setDetail(f)}><EllipsisVertical size={16} /></IconButton></td></tr>)}</tbody>;
        })}</table>
        {!filtered.length && <div className="empty-state"><FileSearch size={30} /><h3>{findings.length === 0 ? 'Нет результатов проверки' : 'Замечаний не найдено'}</h3><p>{findings.length === 0 ? 'Включите правила в разделе «Правила проверки», чтобы увидеть результаты.' : 'Попробуйте изменить условия фильтра.'}</p>{findings.length === 0 ? <button className="secondary-button" onClick={onManageRules}>Управление правилами</button> : hasFilters && <button className="secondary-button" onClick={resetFilters}>Сбросить фильтры</button>}</div>}
      </div><div className="review-footer"><span><Eye size={14} />Проверено <strong>{reviewed} из {findings.length}</strong></span><div className="review-progress-wrap"><div className="review-progress" role="progressbar" aria-label="Прогресс проверки" aria-valuetext={`${reviewed} из ${findings.length}, ${reviewPercent}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={reviewPercent}><i style={{width:`${reviewPercent}%`}} /></div><span>{reviewPercent}%</span></div></div></div>}
      {tab === 'navigation' && <div className="outline-pane" role="tabpanel" tabIndex={0} id="panel-navigation" aria-labelledby="tab-navigation"><div className="pane-heading"><List size={18} /><span>Содержание документа</span></div>{outline.map(section => <button className={page === section.page ? 'current' : ''} key={section.title} onClick={() => { onPage(section.page); setMobilePane('document'); }}><span>{section.title}</span><span className="outline-page">{section.page}<ChevronRight size={15} /></span></button>)}</div>}
      {tab === 'rules' && <div className="inline-rules" role="tabpanel" tabIndex={0} id="panel-rules" aria-labelledby="tab-rules"><div className="pane-heading"><ShieldCheck size={18} /><span>Правила проверки · {rules.length}</span></div><div className="manage-rules-link"><button className="secondary-button" onClick={onManageRules}>Управление правилами</button></div>{rules.map(rule => <button key={rule.id} onClick={() => onEditRule(rule)} aria-label={`Редактировать правило «${rule.title}»`}><span className={`rule-check ${rule.severity}`}><FileCheck2 size={18} /></span><span><strong>{rule.title}</strong><small>{riskLabels[rule.severity]} · {!rule.enabled ? 'Выключено' : findings.some(f=>f.id===rule.id) ? 'Есть результат проверки' : 'Ещё не проверено'}</small></span><ChevronRight size={16} /></button>)}{!rules.length && <div className="empty-state"><p>Добавьте правила в разделе «Правила».</p></div>}</div>}
    </aside>}

    {detail && <Modal title={`Замечание № ${detail.id}`} onClose={() => setDetail(null)}><div className="finding-detail"><span className={`severity-tag ${detail.severity}`}>{severityLabels[detail.severity]}</span><h3>{detail.title}</h3><p>{detail.description}</p><div className="detail-meta"><span>Пункт {detail.clause}</span><span>Страница {detail.page}</span><span>{detail.category}</span></div><h4>Фрагмент документа</h4><blockquote>{detail.quote}</blockquote><h4>На что обратить внимание</h4><p>{detail.recommendation}</p><label className="form-label" htmlFor="detail-status">Статус проверки</label><select id="detail-status" className="form-select" value={statuses[detail.id] ?? 'unseen'} onChange={e => onStatus(detail.id, e.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select><small className="detail-disclaimer">Пример результата проверки. Автоматический анализ не выполнялся.</small></div><div className="modal-actions"><button className="secondary-button" onClick={() => setDetail(null)}>Закрыть</button><button className="primary-button" onClick={() => { select(detail); setDetail(null); }}>К фрагменту</button></div></Modal>}
  </div>;
}
