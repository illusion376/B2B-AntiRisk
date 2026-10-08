'use client';

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { AlertCircle, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronsLeftRight, EllipsisVertical, ExternalLink, Eye, FileCheck2, FileSearch, FileText, Hand, List, LoaderCircle, Maximize, Minimize, Minus, PanelLeftClose, PanelLeftOpen, Plus, RotateCcw, Search, ShieldCheck, X } from 'lucide-react';
import { documentFileUrl, thumbnailUrl } from '@/lib/api';
import { findingSourceLabels, isRiskSeverity, severityLabels, statusLabels } from '@/lib/labels';
import type { CheckRule, DocumentInfo, Finding, OutlineSection, PageContent, ReviewStatus, Severity } from '@/lib/types';
import { riskLabels } from '@/lib/rules';
import { HighlightedText, IconButton, Modal } from './ui';
import { FindingEvidenceBadges } from './shared-badges';
import './review-enhancements.css';
import './live-document.css';

const reviewTabs = [
  { id: 'findings', label: 'Результаты' },
  { id: 'navigation', label: 'Навигация' },
  { id: 'rules', label: 'Правила проверки' },
] as const;
const severityOrder: Severity[] = ['critical', 'warning', 'low', 'unknown', 'ok'];
const noPendingStatuses: ReadonlySet<string> = new Set();
type ReviewTab = typeof reviewTabs[number]['id'];

export type DocumentWorkspaceProps = {
  document: DocumentInfo;
  pageContent: PageContent | null;
  outline: OutlineSection[];
  pageLoading: boolean;
  pageError: string | null;
  onRetryPage: () => void;
  pendingIds?: ReadonlySet<string>;
  rules: CheckRule[];
  onManageRules: () => void;
  onEditRule: (rule: CheckRule) => void;
  page: number;
  selected: string | null;
  search: string;
  findings: Finding[];
  statuses: Record<string, ReviewStatus>;
  onPage: (page: number) => void;
  onSelect: (finding: Finding) => void;
  onStatus: (id: string, status: ReviewStatus) => void;
};

function findingLabel(finding: Finding) {
  return !isRiskSeverity(finding.severity) || finding.number === null ? 'Результат проверки правила' : `Замечание № ${finding.number}`;
}

function PageThumbnail({ documentId, page, hasPreview }: { documentId: string; page: number; hasPreview: boolean }) {
  const [failed, setFailed] = useState(false);
  return <span className="live-thumbnail-paper" aria-hidden="true">
    {hasPreview && !failed
      ? <img src={thumbnailUrl(documentId, page, 160)} loading="lazy" decoding="async" alt="" onError={() => setFailed(true)} />
      : <span className="thumbnail-unavailable"><FileText size={20} /><small>{failed ? 'Нет превью' : page}</small></span>}
  </span>;
}

function PdfPage({ documentId, pageContent, page, zoom, findings, selected, onSelect, onRetry }: {
  documentId: string;
  pageContent: PageContent;
  page: number;
  zoom: number;
  findings: Finding[];
  selected: string | null;
  onSelect: (finding: Finding) => void;
  onRetry: () => void;
}) {
  const [imageState, setImageState] = useState<'loading' | 'ready' | 'error'>('loading');
  const { width, height } = pageContent;
  const hasDimensions = width > 0 && height > 0;
  if (imageState === 'error') return <div className="live-page-state" role="alert">
    <AlertCircle size={28} /><h3>Не удалось загрузить страницу PDF</h3><p>Повторите загрузку или откройте текстовую версию.</p>
    <button className="secondary-button" onClick={onRetry}><RotateCcw size={15} />Повторить</button>
  </div>;
  return <div className="live-pdf-page" style={{ width: `${zoom}%`, minWidth: `${zoom}%`, aspectRatio: hasDimensions ? `${width} / ${height}` : undefined }} aria-busy={imageState === 'loading'}>
    {imageState === 'loading' && <div className="pdf-loading-indicator" role="status"><LoaderCircle size={20} />Загрузка страницы…</div>}
    <img src={thumbnailUrl(documentId, page, 1200)} alt={`Страница ${page} документа`} draggable={false} onLoad={() => setImageState('ready')} onError={() => setImageState('error')} />
    {imageState === 'ready' && hasDimensions && findings.filter(finding => finding.quoteVerified && isRiskSeverity(finding.severity)).flatMap(finding =>
      finding.highlights.filter(highlight => highlight.page === page).flatMap((highlight, highlightIndex) => highlight.rects.map((rect, rectIndex) => {
        if (rect.length !== 4 || !rect.every(Number.isFinite)) return null;
        const left = Math.max(0, Math.min(width, rect[0]));
        const top = Math.max(0, Math.min(height, rect[1]));
        const right = Math.max(left, Math.min(width, rect[2]));
        const bottom = Math.max(top, Math.min(height, rect[3]));
        if (right <= left || bottom <= top) return null;
        return <button
          key={`${finding.id}-${highlightIndex}-${rectIndex}`}
          className={`pdf-finding-highlight ${finding.severity} ${selected === finding.id ? 'selected' : ''}`}
          data-finding={finding.id}
          style={{ left: `${left / width * 100}%`, top: `${top / height * 100}%`, width: `${(right - left) / width * 100}%`, height: `${(bottom - top) / height * 100}%` }}
          title={`${findingLabel(finding)}: ${finding.title}`}
          aria-label={`${findingLabel(finding)}: ${finding.title}`}
          onClick={() => onSelect(finding)}
        />;
      })))
    }
  </div>;
}

export function DocumentWorkspace({ document, pageContent, outline, pageLoading, pageError, onRetryPage, pendingIds = noPendingStatuses, rules, onManageRules, onEditRule, page, selected, search, findings, statuses, onPage, onSelect, onStatus }: DocumentWorkspaceProps) {
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
  const [detailId, setDetailId] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<'document' | 'findings'>('document');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const [viewerMode, setViewerMode] = useState<'pdf' | 'text'>(document.hasPreview ? 'pdf' : 'text');
  const [previewRevision, setPreviewRevision] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchToggleRef = useRef<HTMLButtonElement>(null);
  const tabRefs = useRef<Partial<Record<ReviewTab, HTMLButtonElement | null>>>({});
  const thumbnailRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const previousPage = useRef(page);
  const totalPages = document.totalPages;
  const currentPage = pageContent?.page === page ? pageContent : null;
  const sections = currentPage?.sections ?? [];
  const categories = [...new Set(findings.map(finding => finding.category).filter(Boolean))];
  const filtered = useMemo(() => findings.filter(finding =>
    (category === 'all' || category === finding.category)
    && (severity === 'all' || severity === finding.severity)
    && (status === 'all' || (statuses[finding.id] ?? finding.status) === status)
    && `${finding.title} ${finding.description} ${finding.quote}`.toLocaleLowerCase('ru').includes(filterText.trim().toLocaleLowerCase('ru'))
  ).sort((a, b) => {
    // Successful checks have no display number and remain after numbered findings.
    if (a.number === null) return b.number === null ? 0 : 1;
    if (b.number === null) return -1;
    return order === 'asc' ? a.number - b.number : b.number - a.number;
  }), [findings, category, severity, status, statuses, filterText, order]);
  const activeFilterCount = [category !== 'all', severity !== 'all', status !== 'all', Boolean(filterText.trim())].filter(Boolean).length;
  const hasFilters = activeFilterCount > 0;
  const selectedFinding = findings.find(finding => finding.id === selected);
  const detail = findings.find(finding => finding.id === detailId);
  const riskFindings = findings.filter(finding => isRiskSeverity(finding.severity));
  const unknownCount = findings.filter(finding => finding.severity === 'unknown').length;
  const visibleEvidence = filtered.filter(finding => finding.quoteVerified && isRiskSeverity(finding.severity));
  const reviewed = riskFindings.filter(finding => (statuses[finding.id] ?? finding.status) !== 'unseen').length;
  const reviewPercent = riskFindings.length ? Math.round(reviewed / riskFindings.length * 100) : 0;
  const hasText = sections.some(section => section.paragraphs.some(paragraph => paragraph.text.trim()));

  useEffect(() => {
    setViewerMode(document.hasPreview ? 'pdf' : 'text');
    setDetailId(null);
    setPreviewRevision(0);
  }, [document.id, document.hasPreview]);

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
  }, [page]);

  useEffect(() => {
    if (selectedFinding) setCollapsed(previous => previous.filter(level => level !== selectedFinding.severity));
  }, [selectedFinding]);

  // Text paragraphs are available after their request completes. PDF highlights
  // scroll themselves into view once the image has loaded below.
  useEffect(() => { scrollToSelected(); }, [page, selected, currentPage, viewerMode]);

  function scrollToSelected() {
    const viewport = scrollRef.current;
    if (!viewport || selected === null) return;
    const element = [...viewport.querySelectorAll<HTMLElement>('[data-finding]')].find(item => item.dataset.finding === selected);
    if (!element) return;
    const target = element.getBoundingClientRect();
    const bounds = viewport.getBoundingClientRect();
    if (target.top < bounds.top || target.bottom > bounds.bottom) {
      viewport.scrollTo({ top: viewport.scrollTop + target.top - bounds.top - 16, behavior: 'smooth' });
    }
  }

  function commitPage() {
    const value = Number(pageInput);
    if (!totalPages || !pageInput.trim() || !Number.isFinite(value)) { setPageInput(String(page)); return; }
    const nextPage = Math.max(1, Math.min(totalPages, Math.trunc(value)));
    setPageInput(String(nextPage));
    if (nextPage !== page) onPage(nextPage);
  }
  function retryPage() { setPreviewRevision(value => value + 1); onRetryPage(); }
  function closeSearch() { setFilterText(''); setSearchVisible(false); searchToggleRef.current?.focus(); }
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
  function isLocated(finding: Finding) { return finding.page !== null && finding.page >= 1 && finding.page <= totalPages; }
  function select(finding: Finding) {
    if (!isLocated(finding)) { setDetailId(finding.id); return; }
    onSelect(finding);
    setMobilePane('document');
  }
  function resetFilters() { setCategory('all'); setStatus('all'); setSeverity('all'); setFilterText(''); }
  function returnToFindings() { setMobilePane('findings'); setExpanded(false); setTab('findings'); }
  function openFinding(finding: Finding) { onSelect(finding); setDetailId(finding.id); }
  function reviewStatus(finding: Finding) { return statuses[finding.id] ?? finding.status; }

  return <div className={`document-workspace live-document-workspace ${expanded ? 'reader-expanded' : ''} ${showPages ? '' : 'pages-hidden'} mobile-${mobilePane}`}>
    <div className="mobile-pane-tabs" role="group" aria-label="Панель документа">
      <button aria-pressed={mobilePane === 'document'} className={mobilePane === 'document' ? 'active' : ''} onClick={() => setMobilePane('document')}><FileSearch size={16} />Документ</button>
      <button aria-pressed={mobilePane === 'findings'} className={mobilePane === 'findings' ? 'active' : ''} onClick={returnToFindings}><List size={16} />Результаты <span>{findings.length}</span></button>
    </div>

    {showPages && <aside className="pages-sidebar" aria-label="Страницы документа">
      <div className="panel-title"><span>Страницы</span><IconButton label="Скрыть страницы" onClick={() => setShowPages(false)}><PanelLeftClose size={16} /></IconButton></div>
      <div className="thumbnails">
        {Array.from({ length: totalPages }, (_, index) => index + 1).map(number => <button ref={number === page ? thumbnailRef : undefined} key={number} aria-label={`Страница ${number}`} aria-current={number === page ? 'page' : undefined} className={`thumbnail ${number === page ? 'selected' : ''}`} onClick={() => onPage(number)}>
          <PageThumbnail key={`${document.id}-${number}-${previewRevision}`} documentId={document.id} page={number} hasPreview={document.hasPreview} />
          <span className="thumbnail-label">{number}{riskFindings.some(finding => finding.page === number) && <i />}</span>
        </button>)}
        {!totalPages && <p className="no-page-thumbnails">Нет страниц</p>}
      </div>
    </aside>}

    <section className="reader" aria-label="Просмотр документа">
      <div className="reader-toolbar">
        {!showPages && <IconButton label="Показать страницы" onClick={() => setShowPages(true)}><PanelLeftOpen size={17} /></IconButton>}
        <div className="page-control">
          <IconButton label="Предыдущая страница" onClick={() => onPage(page - 1)} disabled={page <= 1 || !totalPages}><ChevronLeft size={17} /></IconButton>
          <input type="number" aria-label="Номер страницы" min={1} max={totalPages || 1} step={1} disabled={!totalPages} value={totalPages ? pageInput : ''} onChange={event => setPageInput(event.target.value)} onBlur={commitPage} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} />
          <span>/ {totalPages}</span>
          <IconButton label="Следующая страница" onClick={() => onPage(page + 1)} disabled={page >= totalPages}><ChevronRight size={17} /></IconButton>
        </div>
        <div className="toolbar-divider" />
        <div className="zoom-control">
          <IconButton label="Уменьшить масштаб" onClick={() => setZoom(value => Math.max(50, value - 10))} disabled={zoom === 50}><Minus size={16} /></IconButton>
          <button title="Сбросить масштаб" onClick={() => setZoom(100)}>{zoom}%</button>
          <IconButton label="Увеличить масштаб" onClick={() => setZoom(value => Math.min(160, value + 10))} disabled={zoom === 160}><Plus size={16} /></IconButton>
        </div>
        <div className="toolbar-divider" />
        <IconButton label="Перемещать документ" active={hand} aria-pressed={hand} onClick={() => setHand(value => !value)}><Hand size={17} /></IconButton>
        <IconButton label="По ширине страницы" onClick={() => { setZoom(100); scrollRef.current?.scrollTo({ left: 0 }); }}><ChevronsLeftRight size={18} /></IconButton>
        <div className="toolbar-spacer" />
        <IconButton label={expanded ? 'Свернуть документ' : 'Развернуть документ'} onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize size={17} /> : <Maximize size={17} />}</IconButton>
      </div>
      <div className="document-view-controls">
        <div className="document-view-toggle" role="group" aria-label="Представление документа">
          <button className={viewerMode === 'pdf' ? 'active' : ''} aria-pressed={viewerMode === 'pdf'} disabled={!document.hasPreview} onClick={() => setViewerMode('pdf')}>PDF</button>
          <button className={viewerMode === 'text' ? 'active' : ''} aria-pressed={viewerMode === 'text'} onClick={() => setViewerMode('text')}>Текст</button>
        </div>
        {document.hasPreview && <a href={documentFileUrl(document.id)} target="_blank" rel="noopener noreferrer" title="Открыть PDF в новой вкладке"><ExternalLink size={13} />Открыть PDF</a>}
      </div>
      {selectedFinding && <div className={`selected-finding-context ${selectedFinding.severity}`}>
        <span className={`risk-dot ${selectedFinding.severity}`} aria-hidden="true" />
        <button className="selected-finding-title" onClick={() => setDetailId(selectedFinding.id)} title={selectedFinding.title}>
          <span>{findingLabel(selectedFinding)}{selectedFinding.clause ? ` · п. ${selectedFinding.clause}` : ''}{selectedFinding.page === null ? ' · без привязки к странице' : ''}{selectedFinding.severity === 'unknown' ? ' · недостаточно данных' : isRiskSeverity(selectedFinding.severity) && !selectedFinding.quoteVerified ? ' · без подтверждённой цитаты' : ''}</span><strong>{selectedFinding.title}</strong>
        </button>
        <button className="return-to-findings" onClick={returnToFindings} aria-label="Вернуться к замечаниям"><List size={16} /></button>
        <IconButton label="Подробнее о выбранном замечании" onClick={() => setDetailId(selectedFinding.id)}><ChevronRight size={16} /></IconButton>
      </div>}
      <div ref={scrollRef} className={`paper-scroll ${hand ? 'hand-mode' : ''}`} aria-busy={pageLoading}
        onPointerDown={event => { if (!hand || (event.target as HTMLElement).closest('button, a')) return; const element = event.currentTarget; drag.current = { x: event.clientX, y: event.clientY, left: element.scrollLeft, top: element.scrollTop }; element.setPointerCapture(event.pointerId); }}
        onPointerMove={event => { if (drag.current) { event.currentTarget.scrollLeft = drag.current.left - event.clientX + drag.current.x; event.currentTarget.scrollTop = drag.current.top - event.clientY + drag.current.y; } }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
        onLoadCapture={() => requestAnimationFrame(scrollToSelected)}>
        {!totalPages ? <div className="live-page-state"><FileText size={30} /><h3>Страницы пока недоступны</h3><p>{document.errorMessage || 'После обработки документа здесь появится его содержимое.'}</p></div>
          : pageLoading ? <div className="live-page-state" role="status"><LoaderCircle className="live-loading-spinner" size={28} /><h3>Загрузка страницы {page}…</h3></div>
          : pageError ? <div className="live-page-state" role="alert"><AlertCircle size={28} /><h3>Не удалось загрузить страницу</h3><p>{pageError}</p><button className="secondary-button" onClick={retryPage}><RotateCcw size={15} />Повторить</button></div>
          : !currentPage ? <div className="live-page-state"><FileSearch size={28} /><h3>Содержимое страницы недоступно</h3><button className="secondary-button" onClick={retryPage}>Загрузить страницу</button></div>
          : viewerMode === 'pdf' && document.hasPreview ? <PdfPage key={`${document.id}-${page}-${previewRevision}`} documentId={document.id} pageContent={currentPage} page={page} zoom={zoom} findings={visibleEvidence} selected={selected} onSelect={openFinding} onRetry={retryPage} />
          : !hasText ? <div className="live-page-state"><FileSearch size={28} /><h3>Текст страницы не распознан</h3><p>На этой странице нет доступного для поиска текста.</p>{document.hasPreview && <button className="secondary-button" onClick={() => setViewerMode('pdf')}>Показать PDF</button>}</div>
          : <article className="document-paper live-text-paper" style={{ width: `${zoom}%`, minWidth: `${zoom}%`, fontSize: `${zoom * .145}px` }} aria-label={`Текст страницы ${page}`}>
            <div className="paper-running-header"><span>{document.name}</span><span>{currentPage.isOcr ? 'РАСПОЗНАННЫЙ ТЕКСТ' : 'ТЕКСТ ДОКУМЕНТА'}</span></div>
            {sections.map((section, sectionIndex) => <section className="contract-section" key={`${sectionIndex}-${section.title}`}>
              {section.title && <h2>{section.title}</h2>}
              {section.paragraphs.map((paragraph, paragraphIndex) => {
                const paragraphFindings = visibleEvidence.filter(finding => paragraph.findingIds.includes(finding.id));
                const activeFinding = paragraphFindings.find(finding => finding.id === selected) ?? paragraphFindings[0];
                return <div key={`${paragraphIndex}-${paragraph.clause}`} data-finding={activeFinding?.id} className={`contract-paragraph ${activeFinding ? `annotation ${activeFinding.severity}` : ''} ${activeFinding?.id === selected ? 'focused' : ''}`}>
                  {paragraphFindings.length > 0 && <span className="paragraph-finding-markers">{paragraphFindings.map(finding => <button key={finding.id} className={`annotation-marker ${finding.severity}`} aria-label={`${findingLabel(finding)}: ${finding.title}`} onClick={() => openFinding(finding)}>{finding.number ?? '!'}</button>)}</span>}
                  {paragraph.clause && <span className="clause-number">{paragraph.clause}.</span>}
                  <p><HighlightedText text={paragraph.text} query={search} /></p>
                </div>;
              })}
            </section>)}
            <div className="paper-page-number">{page}</div>
          </article>}
      </div>
      <div className="reader-footer"><span>{totalPages ? `Страница ${page} из ${totalPages}` : 'Нет страниц'}</span><span>{viewerMode === 'pdf' ? 'PDF' : currentPage?.isOcr ? 'Распознанный текст' : 'Текст документа'}</span></div>
    </section>

    {!expanded && <aside className="review-panel" aria-label="Проверка документа">
      <div className="review-tabs" role="tablist" aria-label="Раздел проверки">{reviewTabs.map(item => <button ref={element => { tabRefs.current[item.id] = element; }} tabIndex={tab === item.id ? 0 : -1} onKeyDown={event => navigateTabs(event, item.id)} role="tab" id={`tab-${item.id}`} aria-controls={tab === item.id ? `panel-${item.id}` : undefined} aria-selected={tab === item.id} key={item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>{item.label}{item.id === 'findings' && <span>{findings.length}</span>}</button>)}</div>
      {tab === 'findings' && <div role="tabpanel" tabIndex={0} id="panel-findings" aria-labelledby="tab-findings" className="findings-pane">
        <div className="filters">
          <label><span className="sr-only">Категория</span><select value={category} onChange={event => setCategory(event.target.value)}><option value="all">Все категории</option>{categories.map(value => <option key={value}>{value}</option>)}</select><ChevronDown size={14} /></label>
          <label><span className="sr-only">Статус проверки</span><select value={status} onChange={event => setStatus(event.target.value)}><option value="all">Все статусы</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={14} /></label>
          <label><span className="sr-only">Уровень риска</span><select value={severity} onChange={event => setSeverity(event.target.value)}><option value="all">Все уровни</option><option value="critical">Критические</option><option value="warning">Внимание</option><option value="low">Низкий риск</option><option value="unknown">Недостаточно данных</option><option value="ok">Без замечаний</option></select><ChevronDown size={14} /></label>
          <button type="button" ref={searchToggleRef} className={`icon-button ${searchVisible ? 'is-active' : ''}`} aria-label={searchVisible ? 'Закрыть поиск замечаний' : 'Поиск замечаний'} title={searchVisible ? 'Закрыть поиск замечаний' : 'Поиск замечаний'} aria-expanded={searchVisible} aria-controls={searchVisible ? 'finding-search' : undefined} onClick={() => searchVisible ? closeSearch() : setSearchVisible(true)}><Search size={18} /></button>
        </div>
        {searchVisible && <div id="finding-search" className="finding-search field-search" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); closeSearch(); } }}><Search size={16} /><input autoFocus placeholder="Название, описание или цитата" aria-label="Поиск замечаний" value={filterText} onChange={event => setFilterText(event.target.value)} /><IconButton label="Очистить поиск замечаний" disabled={!filterText} onClick={() => setFilterText('')}><X size={15} /></IconButton></div>}
        <div className="filter-summary"><span role="status" aria-live="polite">Результаты: <strong>{filtered.length}</strong> из {findings.length}</span>{hasFilters ? <button onClick={resetFilters}><RotateCcw size={13} />Сбросить фильтры <span className="filter-count">{activeFilterCount}</span></button> : <span className="filter-summary-note">По уровню риска</span>}</div>
        <div className="findings-scroll">
          <table className="findings-table">
            <colgroup><col className="col-number" /><col className="col-severity" /><col /><col className="col-clause" /><col className="col-page" /><col className="col-status" /><col className="col-more" /></colgroup>
            <thead><tr><th aria-sort={order === 'asc' ? 'ascending' : 'descending'}><button aria-label={`Номера внутри групп: ${order === 'asc' ? 'по возрастанию' : 'по убыванию'}. Изменить порядок`} onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}>№ <span>{order === 'asc' ? '↑' : '↓'}</span></button></th><th className="severity-header">Риск</th><th>Замечание</th><th>Пункт</th><th>Стр.</th><th>Статус проверки</th><th aria-label="Действия" /></tr></thead>
            {severityOrder.map(level => {
              const group = filtered.filter(finding => finding.severity === level);
              if (!group.length) return null;
              const isCollapsed = collapsed.includes(level);
              return <tbody key={level}>
                <tr className="group-row"><th colSpan={7}><button onClick={() => setCollapsed(previous => previous.includes(level) ? previous.filter(item => item !== level) : [...previous, level])} aria-expanded={!isCollapsed}><span className={`group-bar ${level}`} /><span>{severityLabels[level]} <em>({group.length})</em></span><ChevronDown size={16} className={isCollapsed ? 'rotated' : ''} /></button></th></tr>
                {!isCollapsed && group.map(finding => <tr key={finding.id} data-selected={selected === finding.id} className={`finding-row ${finding.severity === 'unknown' ? 'unknown-row' : ''} ${selected === finding.id ? 'selected-row' : ''}`}>
                  <td className="number-cell">{finding.number ?? '—'}</td>
                  <td className="severity-cell"><span className={`risk-dot ${finding.severity}`} title={severityLabels[finding.severity]} /><span className="sr-only">{severityLabels[finding.severity]}</span></td>
                  <td className="finding-cell"><button onClick={() => select(finding)} className="finding-link" aria-current={selected === finding.id ? 'true' : undefined}><strong><HighlightedText text={finding.title} query={filterText} /></strong><span><HighlightedText text={finding.description} query={filterText} /></span><FindingEvidenceBadges finding={finding} /><small className="finding-mobile-meta">{finding.clause ? `п. ${finding.clause} · ` : ''}{isLocated(finding) ? `стр. ${finding.page}` : 'Без привязки к странице'}</small></button></td>
                  <td className="clause-cell">{finding.clause ? <button onClick={() => select(finding)}>{finding.clause}</button> : '—'}</td>
                  <td className="page-cell">{isLocated(finding) ? <button onClick={() => select(finding)} aria-label={`Открыть страницу ${finding.page}`}>{finding.page}</button> : <span title="Страница не определена">—</span>}</td>
                  <td className="status-cell"><div className={`review-status ${reviewStatus(finding)}`} aria-busy={pendingIds.has(finding.id)}>
                    <span>{pendingIds.has(finding.id) ? <LoaderCircle className="live-loading-spinner" size={10} /> : reviewStatus(finding) === 'accepted' ? <Check size={10} /> : reviewStatus(finding) === 'dismissed' ? <X size={10} /> : null}</span>
                    <select aria-label={`Статус: ${finding.title}`} disabled={pendingIds.has(finding.id)} value={reviewStatus(finding)} onChange={event => onStatus(finding.id, event.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><ChevronDown size={12} aria-hidden="true" />
                  </div></td>
                  <td className="more-cell"><IconButton label={`Подробнее: ${finding.title}`} onClick={() => setDetailId(finding.id)}><EllipsisVertical size={16} /></IconButton></td>
                </tr>)}
              </tbody>;
            })}
          </table>
          {!filtered.length && <div className="empty-state"><FileSearch size={30} /><h3>{findings.length === 0 ? 'Нет результатов проверки' : 'Замечаний не найдено'}</h3><p>{findings.length === 0 ? 'Результаты появятся после проверки документа выбранными правилами.' : 'Попробуйте изменить условия фильтра.'}</p>{findings.length === 0 ? <button className="secondary-button" onClick={onManageRules}>Управление правилами</button> : hasFilters && <button className="secondary-button" onClick={resetFilters}>Сбросить фильтры</button>}</div>}
        </div>
        <div className="review-footer">
          {riskFindings.length > 0 ? <><span><Eye size={14} />Рассмотрено замечаний <strong>{reviewed} из {riskFindings.length}</strong></span><div className="review-progress-wrap"><div className="review-progress" role="progressbar" aria-label="Прогресс рассмотрения замечаний" aria-valuetext={`${reviewed} из ${riskFindings.length}, ${reviewPercent}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={reviewPercent}><i style={{ width: `${reviewPercent}%` }} /></div><span>{reviewPercent}%</span></div></>
            : <span>{unknownCount > 0 ? `Результатов без вывода: ${unknownCount}` : findings.length ? 'Замечаний по завершённым проверкам нет' : 'Нет результатов проверки'}</span>}
        </div>
      </div>}
      {tab === 'navigation' && <div className="outline-pane" role="tabpanel" tabIndex={0} id="panel-navigation" aria-labelledby="tab-navigation">
        <div className="pane-heading"><List size={18} /><span>Содержание документа</span></div>
        {outline.map((section, index) => <div className="live-outline-section" key={`${section.page}-${index}`}>
          <button className={page === section.page ? 'current' : ''} onClick={() => { onPage(section.page); setMobilePane('document'); }}><span>{section.title || `Страница ${section.page}`}</span><span className="outline-page">{section.page}<ChevronRight size={15} /></span></button>
          {section.clauses.map((clause, clauseIndex) => <button className={`live-outline-clause ${page === clause.page ? 'current' : ''}`} key={`${clause.clause}-${clauseIndex}`} onClick={() => { onPage(clause.page); setMobilePane('document'); }}><span>{clause.clause}{clause.title ? ` · ${clause.title}` : ''}</span><span className="outline-page">{clause.page}</span></button>)}
        </div>)}
        {!outline.length && <div className="empty-state"><List size={28} /><h3>Оглавление не найдено</h3><p>Используйте миниатюры или номер страницы для перехода по документу.</p></div>}
      </div>}
      {tab === 'rules' && <div className="inline-rules" role="tabpanel" tabIndex={0} id="panel-rules" aria-labelledby="tab-rules">
        <div className="pane-heading"><ShieldCheck size={18} /><span>Правила проверки · {rules.length}</span></div><div className="manage-rules-link"><button className="secondary-button" onClick={onManageRules}>Управление правилами</button></div>
        {rules.map(rule => <button key={rule.id} onClick={() => onEditRule(rule)} aria-label={`Редактировать правило «${rule.title}»`}><span className={`rule-check ${rule.severity}`}><FileCheck2 size={18} /></span><span><strong>{rule.title}</strong><small>{riskLabels[rule.severity]} · {!rule.enabled ? 'Выключено' : findings.some(finding => finding.ruleId === rule.id) ? 'Есть результат проверки' : 'Нет результата проверки'}</small></span><ChevronRight size={16} /></button>)}
        {!rules.length && <div className="empty-state"><p>Добавьте правила в разделе «Правила».</p></div>}
      </div>}
    </aside>}

    {detail && <Modal title={findingLabel(detail)} onClose={() => setDetailId(null)}>
      <div className="finding-detail">
        <span className={`severity-tag ${detail.severity}`}>{severityLabels[detail.severity]}</span>
        {detail.severity === 'unknown' && <p className="unknown-result-explanation">По этому правилу пока нельзя сделать вывод о наличии или отсутствии риска. Проверьте причину и исходный документ.</p>}
        <h3>{detail.title}</h3><p>{detail.description}</p>
        <div className="detail-meta">{detail.clause && <span>Пункт {detail.clause}</span>}<span>{isLocated(detail) ? `Страница ${detail.page}` : 'Страница не определена'}</span>{detail.category && <span>{detail.category}</span>}</div>
        <div className={`finding-evidence ${detail.source === 'ERROR' ? 'evidence-error' : ''} ${detail.severity === 'unknown' ? 'evidence-unknown' : ''}`}>
          <span>Источник: <strong>{findingSourceLabels[detail.source] ?? (detail.source || 'Не указан')}</strong></span>
          {detail.quote && <span className={detail.quoteVerified ? detail.severity === 'unknown' ? 'quote-located-neutral' : 'quote-verified' : 'quote-unverified'}>{detail.quoteVerified ? <ShieldCheck size={14} /> : <AlertCircle size={14} />}{detail.quoteVerified ? detail.severity === 'unknown' ? 'Цитата найдена; вывод по правилу не определён' : 'Цитата найдена в документе' : 'Цитата не подтверждена в тексте документа'}</span>}
        </div>
        <h4>Фрагмент документа</h4>
        {detail.quote ? <blockquote className={!detail.quoteVerified ? 'unverified-quote' : undefined}>{detail.quote}</blockquote> : <p className="missing-quote">Цитата для этого результата отсутствует.</p>}
        {detail.quoteVerified && <p className="quote-evidence-note">Совпадение цитаты подтверждает её наличие в документе. Вывод по правилу приведён в обосновании ниже.</p>}
        {detail.comment && detail.comment !== detail.description && <><h4>Обоснование</h4><p>{detail.comment}</p></>}
        {detail.legalReference && <><h4>Ссылка на норму</h4><p>{detail.legalReference}</p></>}
        {detail.recommendation && <><h4>На что обратить внимание</h4><p>{detail.recommendation}</p></>}
        <label className="form-label" htmlFor="detail-status">Статус проверки</label>
        <select id="detail-status" className="form-select" disabled={pendingIds.has(detail.id)} aria-busy={pendingIds.has(detail.id)} value={reviewStatus(detail)} onChange={event => onStatus(detail.id, event.target.value as ReviewStatus)}>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        {pendingIds.has(detail.id) && <small className="detail-saving-status" role="status">Сохранение статуса…</small>}
      </div>
      <div className="modal-actions"><button className="secondary-button" onClick={() => setDetailId(null)}>Закрыть</button>{isLocated(detail) && <button className="primary-button" onClick={() => { select(detail); setDetailId(null); }}>{detail.quoteVerified && isRiskSeverity(detail.severity) ? 'К фрагменту' : 'К странице'}</button>}</div>
    </Modal>}
  </div>;
}
