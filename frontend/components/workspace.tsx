'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, BookOpenCheck, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clock3, Download, EllipsisVertical, FileText, Files, History, Info, Pencil, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import { documentInfo, findings, getPageSections, statusLabels } from '@/lib/mock-data';
import type { CheckRule, Finding, HistoryEntry, Project, ProjectDraft, ProjectFile, ReviewStatus, RuleDraft, View } from '@/lib/types';
import { downloadReport } from '@/lib/report';
import { DocumentWorkspace } from './document-workspace';
import { IconButton, Modal } from './ui';
import { useWorkspaceTools } from './workspace-tools';
import { applyRules, initialWorkspace, parseWorkspace, STORAGE_KEY } from '@/lib/rules';
import { RulesManager, RuleEditor, DeleteRuleDialog } from './rules-manager';
import { ProjectsView, NewProjectDialog } from './projects-view';
import { ProjectFilesView } from './project-files';
import { DEMO_PROJECT_ID, DEMO_FILE_ID, fileType, validateUpload } from '@/lib/projects';

export function Workspace() {
  const [view, setView] = useState<View>('documents');
  const [page, setPage] = useState(18);
  const [selected, setSelected] = useState<number | null>(1);
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const {projects, statuses, rules} = workspace;
  const name = projects.find(project=>project.id===DEMO_PROJECT_ID)?.files.find(file=>file.id===DEMO_FILE_ID)?.name ?? documentInfo.name;
  const [activeProjectId, setActiveProjectId] = useState(DEMO_PROJECT_ID);
  const [draftName, setDraftName] = useState(name);
  const [restored, setRestored] = useState(false);
  const [storageWarning, setStorageWarning] = useState('');
  const canPersist = useRef(true);
  const [ruleDialog, setRuleDialog] = useState<{mode:'create'} | {mode:'edit'|'delete'; rule:CheckRule} | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([
    { id: 'checked', title: 'Проверка документа завершена', detail: '20 правил · 3 критических замечания · 5 требуют внимания', time: '12:36' },
    { id: 'opened', title: 'Документ добавлен', detail: 'Проект контракта.pdf · 54 страницы', time: '12:34' },
  ]);
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [popover, setPopover] = useState<'notifications' | 'profile' | 'document' | null>(null);
  const [modal, setModal] = useState<'rename' | 'info' | 'create-project' | null>(null);
  const [toast, setToast] = useState('');
  const [unread, setUnread] = useState(true);
  const headerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const eventCounter = useRef(0);
  const activeFindings = useMemo(() => applyRules(findings, rules), [rules]);
  const activeProject = projects.find(project=>project.id===activeProjectId) ?? projects[0];
  const categories = [...new Set(rules.map(rule => rule.category))];

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = parseWorkspace(raw);
        if (saved) setWorkspace(saved);
        else { canPersist.current = false; setStorageWarning('Сохранённые настройки не удалось прочитать. Изменения действуют до обновления страницы.'); }
      }
    } catch { canPersist.current = false; setStorageWarning('Хранилище браузера недоступно. Изменения действуют до обновления страницы.'); }
    setRestored(true);
  }, []);
  useEffect(() => {
    if (!restored || !canPersist.current) return;
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace)); setStorageWarning(''); }
    catch { setStorageWarning('Не удалось сохранить изменения в браузере. Не закрывайте вкладку.'); }
  }, [workspace, restored]);

  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 3500); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === 'Escape') { setPopover(null); setSearchOpen(false); }
    };
    const click = (e: MouseEvent) => {
      if (!headerRef.current?.contains(e.target as Node)) { setPopover(null); setSearchOpen(false); }
    };
    window.addEventListener('keydown', key); window.addEventListener('click', click);
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('click', click); };
  }, []);

  const searchResults = useMemo(() => {
    if (search.trim().length < 2) return [];
    const query = search.trim().toLocaleLowerCase('ru');
    return Array.from({ length: documentInfo.pages }, (_, i) => i + 1).flatMap(p => getPageSections(p).flatMap(section => section.paragraphs.filter(paragraph => paragraph.text.toLocaleLowerCase('ru').includes(query)).map(paragraph => ({ page: p, ...paragraph }))));
  }, [search]);

  function addHistory(title: string, detail: string) {
    const entry = { id: `event-${++eventCounter.current}`, title, detail, time: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) };
    setHistory(previous => [entry, ...previous]);
  }
  function changeStatus(id: number, status: ReviewStatus) {
    if ((statuses[id] ?? 'unseen') === status) return;
    setWorkspace(previous => ({...previous, statuses:{...previous.statuses,[id]:status}}));
    addHistory('Статус замечания изменён', `${rules.find(rule => rule.id === id)?.title} · ${statusLabels[status]}`);
    setToast(`Статус: ${statusLabels[status].toLowerCase()}`);
  }
  function selectFinding(finding: Finding) { setActiveProjectId(DEMO_PROJECT_ID); setPage(finding.page); setSelected(finding.id); setView('document'); }
  function navigatePage(value: number) { setActiveProjectId(DEMO_PROJECT_ID); setPage(Math.min(documentInfo.pages, Math.max(1, Math.round(value)))); setSelected(null); setView('document'); }
  function exportReport() { downloadReport(name, activeFindings, statuses); setToast('Отчёт CSV скачан'); addHistory('Отчёт скачан', `${activeFindings.length} правил · формат CSV`); }
  function saveRule(draft: RuleDraft) {
    if (!ruleDialog || ruleDialog.mode === 'delete') return;
    const editedId = ruleDialog.mode === 'edit' ? ruleDialog.rule.id : null;
    setWorkspace(previous => editedId !== null
      ? {...previous,rules:previous.rules.map(rule => rule.id === editedId ? {...draft,id:editedId} : rule)}
      : {...previous,rules:[...previous.rules,{...draft,id:previous.nextRuleId}],nextRuleId:previous.nextRuleId+1});
    addHistory(editedId !== null ? 'Правило изменено' : 'Правило добавлено',draft.title);
    setRuleDialog(null); setToast(editedId !== null ? 'Изменения правила сохранены' : 'Правило добавлено');
  }
  function deleteRule() {
    if (!ruleDialog || ruleDialog.mode !== 'delete') return;
    const rule = ruleDialog.rule;
    setWorkspace(previous => {
      const nextStatuses = {...previous.statuses}; delete nextStatuses[rule.id];
      return {...previous,rules:previous.rules.filter(item=>item.id!==rule.id),statuses:nextStatuses};
    });
    if (selected === rule.id) setSelected(null);
    addHistory('Правило удалено',rule.title); setRuleDialog(null); setToast('Правило удалено');
  }
  function toggleRule(rule: CheckRule) {
    setWorkspace(previous=>({...previous,rules:previous.rules.map(item=>item.id===rule.id?{...item,enabled:!item.enabled}:item)}));
    addHistory(rule.enabled?'Правило отключено':'Правило включено',rule.title);
  }
  function openProject(project: Project) { setActiveProjectId(project.id); setView('project'); setSearch(''); setPopover(null); }
  function openDemo() { setActiveProjectId(DEMO_PROJECT_ID); setView('document'); setPage(18); setSelected(1); setSearch(''); }
  function createProject(draft: ProjectDraft): string | void {
    if (projects.some(project=>project.title.toLocaleLowerCase('ru')===draft.title.toLocaleLowerCase('ru'))) return 'Проект с таким названием уже существует.';
    const project: Project = {...draft,id:crypto.randomUUID(),updatedAt:Date.now(),files:[]};
    setWorkspace(previous=>({...previous,projects:[project,...previous.projects]}));
    setModal(null); openProject(project); addHistory('Проект создан',project.title); setToast('Проект создан. Добавьте документы.');
  }
  function uploadFiles(files: File[]): string[] {
    const errors: string[] = [];
    const added: ProjectFile[] = [];
    const projectId = activeProject.id;
    const now = Date.now();
    for (const file of files) {
      const error = validateUpload(file,[...activeProject.files,...added]);
      if (error) { errors.push(`${file.name}: ${error}`); continue; }
      added.push({id:crypto.randomUUID(),name:file.name,type:fileType(file.name)!,size:file.size,source:'upload',addedAt:now});
    }
    if (added.length) {
      setWorkspace(previous=>({...previous,projects:previous.projects.map(project=>project.id===projectId?{...project,files:[...project.files,...added],updatedAt:now}:project)}));
      addHistory('Файлы добавлены в проект',`${activeProject.title} · ${added.map(file=>file.name).join(', ')} · демо-обработка`);
      setToast(`Добавлено файлов: ${added.length}. Началась демо-обработка.`);
    }
    return errors;
  }
  useWorkspaceTools({ page, activeFindings, statuses, navigatePage, selectFinding, changeStatus });

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">К содержимому</a>
    <div ref={headerRef}>
      <header className="topbar">
        <button className="brand" onClick={() => setView('documents')} aria-label="B2B AntiRisk — все проекты">
          <span className="traffic-logo" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>B2B AntiRisk</strong></span>
        </button>
        <nav className="main-nav" aria-label="Основная навигация">
          {([{id:'documents',label:'Документы',Icon:Files},{id:'rules',label:'Правила',Icon:BookOpenCheck},{id:'history',label:'История',Icon:History}] as const).map(item => <button key={item.id} className={view === item.id || ((view === 'project' || view === 'document') && item.id === 'documents') ? 'active' : ''} aria-current={view === item.id || ((view === 'project' || view === 'document') && item.id === 'documents') ? 'page' : undefined} onClick={() => setView(item.id)}><item.Icon size={18} /><span>{item.label}</span></button>)}
        </nav>
        <div className="topbar-right">
          {view === 'document' && <div className="global-search">
            <Search size={17} aria-hidden="true" />
            <input ref={searchRef} placeholder="Поиск по документу..." aria-label="Поиск по документу" value={search} onFocus={() => setSearchOpen(true)} onChange={e => { setSearch(e.target.value); setSearchOpen(true); }} />
            {search ? <button aria-label="Очистить поиск" onClick={() => setSearch('')}><X size={15} /></button> : <kbd>⌘ K</kbd>}
            {searchOpen && search.length >= 2 && <div className="search-results popover">
              <div className="popover-heading">Найдено фрагментов: {searchResults.length}</div>
              {searchResults.slice(0, 25).map((result, index) => <button key={`${result.page}-${index}`} onClick={() => { navigatePage(result.page); setSearchOpen(false); }}><FileText size={17} /><span><strong>Страница {result.page} · п. {result.clause}</strong><small>{result.text}</small></span><ChevronRight size={15} /></button>)}
              {searchResults.length === 0 && <p className="muted empty-small">Ничего не найдено. Попробуйте другое слово.</p>}
            </div>}
          </div>}
          <div className="popover-anchor"><IconButton label="Уведомления" active={popover === 'notifications'} onClick={() => { setPopover(popover === 'notifications' ? null : 'notifications'); setUnread(false); }}><Bell size={20} />{unread && <span className="notification-dot" />}</IconButton>
            {popover === 'notifications' && <div className="popover notifications"><div className="popover-heading">Уведомления <CheckCheck size={16} /></div><button onClick={() => { openDemo(); setPopover(null); }}><span className="notification-icon"><ShieldCheck size={21} /></span><span><strong>Проверка завершена</strong><small>В проекте контракта замечаний: {activeFindings.filter(f=>f.severity!=='ok').length}.</small><em>4 октября, 12:36 · демо</em></span></button></div>}
          </div>
          <div className="popover-anchor"><button className="profile-button" onClick={() => setPopover(popover === 'profile' ? null : 'profile')} aria-label="Профиль" aria-expanded={popover === 'profile'}><span className="avatar">ИА</span><ChevronDown size={15} /></button>
            {popover === 'profile' && <div className="popover profile-popover"><strong>Иван Александров</strong><span className="muted">Демонстрационный профиль</span><div className="popover-divider" /><button onClick={() => { setModal('info'); setPopover(null); }}><CircleHelp size={17} />О рабочем пространстве</button></div>}
          </div>
        </div>
      </header>
      {(view === 'project' || view === 'document') && <div className="project-breadcrumb"><button onClick={()=>setView('documents')}><Files size={14} />Документы</button><ChevronRight size={13} />{view==='document'?<><button onClick={()=>setView('project')}>{activeProject.title}</button><ChevronRight size={13}/><span>Просмотр документа</span></>:<span>{activeProject.title}</span>}</div>}
      {view === 'document' && <section className="document-heading" aria-label="Текущий документ">
        <div className="document-icon"><FileText size={29} strokeWidth={1.4} /><span>PDF</span></div>
        <div className="document-heading-text"><div className="document-title-line"><h1>{name}</h1><span className="demo-badge">Демо</span></div><p>54 страницы <span>·</span> Проверено по {activeFindings.length} правилам</p><small>4 октября, 12:36</small></div>
        <div className="document-actions"><button className="primary-button" onClick={exportReport}><Download size={17} /><span>Скачать отчёт</span></button><div className="popover-anchor"><IconButton label="Действия с документом" className="outlined" onClick={() => setPopover(popover === 'document' ? null : 'document')}><EllipsisVertical size={20} /></IconButton>
          {popover === 'document' && <div className="popover document-menu"><button onClick={() => { setDraftName(name.replace(/\.pdf$/i, '')); setModal('rename'); setPopover(null); }}><Pencil size={16} />Переименовать</button><button onClick={() => { setModal('info'); setPopover(null); }}><Info size={16} />О документе</button></div>}
        </div></div>
      </section>}
    </div>

    <main id="main-content" className="main-content">
      {view === 'documents' && <ProjectsView projects={projects} onOpen={openProject} onCreate={()=>setModal('create-project')} riskCount={activeFindings.filter(f=>f.severity!=='ok').length} />}
      {view === 'project' && <ProjectFilesView key={activeProject.id} project={activeProject} onUpload={uploadFiles} onOpenDemo={openDemo} />}
      {view === 'document' && <DocumentWorkspace page={page} selected={selected} search={search} findings={activeFindings} statuses={statuses} onPage={navigatePage} onSelect={selectFinding} onStatus={changeStatus} rules={rules} onManageRules={()=>setView('rules')} onEditRule={rule=>setRuleDialog({mode:'edit',rule})} />}
      {view === 'rules' && <RulesManager rules={rules} onAdd={()=>setRuleDialog({mode:'create'})} onEdit={rule=>setRuleDialog({mode:'edit',rule})} onDelete={rule=>setRuleDialog({mode:'delete',rule})} onToggle={toggleRule} />}
      {view === 'history' && <section className="secondary-view history-view"><div className="view-title"><div><span className="eyebrow">ЖУРНАЛ ДЕЙСТВИЙ</span><h1>История действий</h1><p>Проверки, решения по замечаниям и скачанные отчёты.</p></div><span className="count-chip"><Clock3 size={16} />Текущая сессия</span></div><div className="timeline-label">Текущая сессия</div><ol className="timeline">{history.map((entry, index) => <li key={entry.id}><span className={`timeline-icon ${index === 0 ? 'latest' : ''}`}><History size={18} /></span><div><h3>{entry.title}</h3><p>{entry.detail}</p></div><time>{entry.time}</time></li>)}</ol></section>}
    </main>
    <footer className="statusbar"><span><span className="local-indicator" />Деморежим обработки</span><span><ShieldCheck size={13} />Сохранение в этом браузере</span><button onClick={() => setModal('info')}><CircleHelp size={13} />Помощь</button></footer>
    {modal === 'create-project' && <NewProjectDialog onCreate={createProject} onClose={()=>setModal(null)} />}
    {storageWarning && <div className="storage-warning" role="alert">{storageWarning}</div>}
    {ruleDialog && ruleDialog.mode !== 'delete' && <RuleEditor rule={ruleDialog.mode==='edit'?ruleDialog.rule:null} categories={categories} onSave={saveRule} onClose={()=>setRuleDialog(null)} />}
    {ruleDialog?.mode==='delete' && <DeleteRuleDialog rule={ruleDialog.rule} onConfirm={deleteRule} onClose={()=>setRuleDialog(null)} />}
    {toast && <div className="toast" role="status"><span><Check size={16} /></span>{toast}<button aria-label="Скрыть уведомление" onClick={() => setToast('')}><X size={16} /></button></div>}

    {modal === 'rename' && <Modal title="Переименовать документ" onClose={() => setModal(null)}><form onSubmit={e => { e.preventDefault(); const value = draftName.trim().replace(/\.pdf$/i, ''); if (!value) return; setWorkspace(previous=>({...previous,projects:previous.projects.map(project=>project.id===DEMO_PROJECT_ID?{...project,updatedAt:Date.now(),files:project.files.map(file=>file.id===DEMO_FILE_ID?{...file,name:`${value}.pdf`}:file)}:project)})); addHistory('Документ переименован', `${value}.pdf`); setModal(null); setToast('Название документа изменено'); }}><label className="form-label" htmlFor="document-name">Название документа</label><div className="name-input"><input id="document-name" autoFocus required maxLength={100} value={draftName} onChange={e => setDraftName(e.target.value)} /><span>.pdf</span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>Отмена</button><button className="primary-button" disabled={!draftName.trim()}>Сохранить</button></div></form></Modal>}
    {modal === 'info' && <Modal title="О рабочем пространстве" onClose={() => setModal(null)}><div className="info-content"><div className="info-file"><FileText size={34} /><div><strong>{name}</strong><span>54 страницы · демонстрационный пример</span></div></div><p>B2B AntiRisk — рабочее пространство для проектов и проверки документов. Текст документа и результаты проверки — тестовые данные.</p><p>Нажмите на замечание, чтобы перейти к нужному фрагменту. В меню замечания можно посмотреть подробности и изменить статус. Поиск работает по тексту всех страниц.</p><div className="info-tip"><SlidersHorizontal size={20} /><span>Проекты, сведения о файлах, правила и статусы сохраняются в текущем браузере. Содержимое файлов не отправляется на сервер. Обработка PDF, TXT и ZIP имитируется; результаты анализа не формируются. История доступна в текущей сессии.</span></div></div><div className="modal-actions"><button className="primary-button" onClick={() => setModal(null)}>Понятно</button></div></Modal>}
  </div>;
}
