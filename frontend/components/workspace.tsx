'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {AlertCircle,Check,ChevronDown,ChevronRight,CircleHelp,Clock3,Download,EllipsisVertical,FileText,Files,History,LoaderCircle,Menu,Pencil,RefreshCw,Search,ShieldCheck,X} from 'lucide-react';
import {api,errorMessage} from '@/lib/api';
import type {AnalysisMode,CheckRule,DocumentInfo,Finding,Project,ProjectDraft,ReportFormat,ReportModeId,ReviewStatus,RuleDraft,SearchResponse,View} from '@/lib/types';
import {DocumentWorkspace} from './document-workspace';
import {IconButton,Modal} from './ui';
import {useWorkspaceTools} from './workspace-tools';
import {RulesManager,RuleEditor,DeleteRuleDialog} from './rules-manager';
import {ProjectsView,NewProjectDialog} from './projects-view';
import {ProjectFilesView} from './project-files';
import {DashboardSidebar} from './dashboard-sidebar';
import {useWorkspaceNavigation} from './use-workspace-navigation';
import {useLiveDocument,useWorkspaceData} from './use-workspace-data';
import {useAnalysisModes} from './use-analysis-modes';
import {SettingsView} from './settings-view';
import './dashboard.css';
import './integration.css';

const dateTime=(value:number|string)=>new Date(value).toLocaleString('ru-RU',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'});
function ErrorNotice({message,onRetry}:{message:string;onRetry?:()=>void}) {
  return <div className="api-error" role="alert"><AlertCircle size={19}/><span>{message}</span>{onRetry&&<button className="secondary-button" onClick={onRetry}><RefreshCw size={15}/>Повторить</button>}</div>;
}
export function Workspace() {
  const {view,page,projectId,documentId,findingId,navigate}=useWorkspaceNavigation();
  const data=useWorkspaceData();
  const analysisModes=useAnalysisModes();
  const selectedAnalysisMode=analysisModes.selectedMode;
  const {projects,rules,history,user,reportModes}=data;
  const live=useLiveDocument(view==='document'?documentId:null,page);
  const activeDocument=live.document;
  const activeProject=projects.find(project=>project.id===projectId);
  const statuses=useMemo(()=>Object.fromEntries(live.findings.map(f=>[f.id,f.status])),[live.findings]);
  const [dashboardQuery,setDashboardQuery]=useState('');
  const [search,setSearch]=useState('');
  const [searchOpen,setSearchOpen]=useState(false);
  const [searchResults,setSearchResults]=useState<SearchResponse|null>(null);
  const [searchLoading,setSearchLoading]=useState(false);
  const [searchError,setSearchError]=useState<string|null>(null);
  const [sidebarOpen,setSidebarOpen]=useState(false);
  const [popover,setPopover]=useState<'profile'|'document'|null>(null);
  const [modal,setModal]=useState<'rename'|'info'|'create-project'|'report'|null>(null);
  const [ruleDialog,setRuleDialog]=useState<{mode:'create'}|{mode:'edit'|'delete';rule:CheckRule}|null>(null);
  const [draftName,setDraftName]=useState('');
  const [saving,setSaving]=useState(false);
  const [modalError,setModalError]=useState<string|null>(null);
  const [actionError,setActionError]=useState<string|null>(null);
  const [toast,setToast]=useState('');
  const [reportMode,setReportMode]=useState<ReportModeId>('detailed');
  const [reportFormat,setReportFormat]=useState<ReportFormat>('docx');
  const [includeDismissed,setIncludeDismissed]=useState(false);
  const [pendingIds,setPendingIds]=useState<ReadonlySet<string>>(new Set());
  const pending=useRef(new Set<string>());
  const headerRef=useRef<HTMLDivElement>(null);
  const searchRef=useRef<HTMLInputElement>(null);
  const categories=[...new Set(rules.map(rule=>rule.category))];
  const modeInfo=reportModes.find(mode=>mode.id===reportMode);
  const setView=(next:View)=>{navigate({view:next});setPopover(null);setSearchOpen(false);setActionError(null);};
  const openProject=(project:Project)=>navigate({view:'project',projectId:project.id,documentId:null,page:1,findingId:null});
  const openDocument=(document:DocumentInfo)=>navigate({view:'document',projectId,documentId:document.id,page:1,findingId:null});
  const navigatePage=(next:number)=>navigate({page:Math.max(1,Math.min(activeDocument?.totalPages||1,next)),findingId:null});
  const selectFinding=(finding:Finding)=>navigate({findingId:finding.id,...(finding.page?{page:finding.page}:{})});
  const refreshAll=()=>{data.refresh();live.refresh();analysisModes.refresh();};
  const openModal=(next:typeof modal)=>{setModalError(null);setModal(next);setPopover(null);};
  useEffect(()=>{
    const header=headerRef.current;if(!header)return;
    const observer=new ResizeObserver(()=>header.closest<HTMLElement>('.app-shell')?.style.setProperty('--header-height',`${header.offsetHeight}px`));
    observer.observe(header);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const onKey=(event:KeyboardEvent)=>{
      if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();searchRef.current?.focus();}
      if(event.key==='Escape'){setPopover(null);setSearchOpen(false);setSidebarOpen(false);}
    };window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey);
  },[]);
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),4500);return()=>clearTimeout(timer);},[toast]);
  useEffect(()=>{setSearch('');setSearchResults(null);setActionError(null);setSearchOpen(false);},[documentId]);
  useEffect(()=>{setModal(null);setRuleDialog(null);setPopover(null);},[view,projectId,documentId]);
  useEffect(()=>{if(activeDocument&&activeDocument.totalPages>0&&page>activeDocument.totalPages)navigate({page:activeDocument.totalPages},true);},[activeDocument,page,navigate]);
  useEffect(()=>{
    setSearchResults(null);setSearchError(null);
    if(view!=='document'||!documentId||search.trim().length<2||activeDocument?.phase!=='ready'){setSearchLoading(false);return;}
    const controller=new AbortController();setSearchLoading(true);
    const timer=setTimeout(()=>{api.searchDocument(documentId,search.trim(),{signal:controller.signal}).then(result=>{if(!controller.signal.aborted)setSearchResults(result);}).catch(cause=>{if(!controller.signal.aborted)setSearchError(errorMessage(cause));}).finally(()=>{if(!controller.signal.aborted)setSearchLoading(false);});},300);
    return()=>{clearTimeout(timer);controller.abort();};
  },[documentId,view,search,activeDocument?.phase]);
  async function changeStatus(id:string,status:ReviewStatus){
    if(pending.current.has(id))throw new Error('Изменение этого замечания уже сохраняется.');
    pending.current.add(id);setPendingIds(new Set(pending.current));setActionError(null);
    try{const finding=await api.updateFinding(id,{status});live.refresh();live.replaceFinding(finding);data.refresh();setToast('Решение по замечанию сохранено');}
    catch(cause){setActionError(errorMessage(cause));throw cause;}
    finally{pending.current.delete(id);setPendingIds(new Set(pending.current));}
  }
  async function createProject(draft:ProjectDraft){try{const project=await api.createProject(draft);data.refresh();openProject(project);setModal(null);setToast('Проект создан');}catch(cause){return errorMessage(cause);}}
  async function uploadFiles(files:File[]){const result=await api.uploadFiles(projectId,files);data.refresh();if(result.files.length)setToast(`Загружено файлов: ${result.files.length}`);return result.errors.map(error=>`${error.name}: ${error.detail}`);}
  async function startAnalysis(mode:AnalysisMode){try{await api.startProjectAnalysis(projectId,{analysisMode:mode});setToast('Анализ запущен');}finally{refreshAll();}}
  async function rerunProject(mode:AnalysisMode){try{await api.rerunProject(projectId,{analysisMode:mode});setToast('Повторная проверка запущена');}finally{refreshAll();}}
  async function toggleRule(rule:CheckRule){await api.updateRule(rule.id,{enabled:!rule.enabled});refreshAll();}
  async function saveRule(draft:RuleDraft){try{if(ruleDialog?.mode==='edit')await api.updateRule(ruleDialog.rule.id,draft);else await api.createRule(draft);refreshAll();setRuleDialog(null);setToast('Правило сохранено');}catch(cause){return errorMessage(cause);}}
  async function deleteRule(){if(ruleDialog?.mode!=='delete')return;try{await api.deleteRule(ruleDialog.rule.id);refreshAll();setRuleDialog(null);setToast('Правило удалено');}catch(cause){return errorMessage(cause);}}
  async function renameDocument(event:React.FormEvent){event.preventDefault();if(!documentId||saving)return;setSaving(true);setModalError(null);try{await api.renameDocument(documentId,draftName.trim());refreshAll();setModal(null);setToast('Название сохранено');}catch(cause){setModalError(errorMessage(cause));}finally{setSaving(false);}}
  async function exportReport(event:React.FormEvent){event.preventDefault();if(!documentId||saving)return;setSaving(true);setModalError(null);try{await api.downloadReport(documentId,{mode:reportMode,format:reportFormat,includeDismissed});data.refresh();setModal(null);setToast('Отчёт скачан');}catch(cause){setModalError(errorMessage(cause));}finally{setSaving(false);}}
  useWorkspaceTools({documentId:view==='document'?documentId:null,page,activeFindings:live.findings,statuses,navigatePage,selectFinding,changeStatus});
  const shell=<div className={`app-shell dashboard-shell${view==='document'?' analysis-shell':''}`}>
    <a className="skip-link" href="#main-content" onClick={event=>{event.preventDefault();document.getElementById('main-content')?.focus();}}>К содержимому</a>
    <DashboardSidebar view={view} user={user} projectCount={projects.length} ruleCount={rules.length} open={sidebarOpen} onClose={()=>setSidebarOpen(false)} onNavigate={setView} onCreate={()=>openModal('create-project')} onHelp={()=>openModal('info')}/>
    <div ref={headerRef} className="dashboard-header"><header className="topbar">
      <button className="dashboard-menu-button" aria-label="Открыть меню" aria-controls="workspace-sidebar" aria-expanded={sidebarOpen} onClick={()=>setSidebarOpen(!sidebarOpen)}><Menu size={20}/></button>
      {view!=='document'?<label className="dashboard-search"><Search size={15}/><input ref={searchRef} aria-label="Поиск проектов и документов" placeholder="Поиск проектов и документов" value={dashboardQuery} onChange={event=>{setDashboardQuery(event.target.value);if(view!=='documents')setView('documents');}}/><kbd>⌘ K</kbd>{dashboardQuery&&<button aria-label="Очистить поиск" onClick={()=>setDashboardQuery('')}><X size={13}/></button>}</label>:<div className="global-search"><Search size={17}/><input ref={searchRef} maxLength={200} placeholder="Поиск по документу…" aria-label="Поиск по документу" value={search} onFocus={()=>setSearchOpen(true)} onChange={event=>{setSearch(event.target.value);setSearchOpen(true);}}/>{search?<button aria-label="Очистить поиск" onClick={()=>setSearch('')}><X size={15}/></button>:<kbd>⌘ K</kbd>}
      {searchOpen&&search.trim().length>=2&&<div className="search-results popover"><div className="popover-heading">{searchLoading?'Ищем фрагменты…':`Найдено фрагментов: ${searchResults?.total??0}`}</div>{searchError&&<p role="alert" className="empty-small">{searchError}</p>}{searchResults?.hits.map((hit,index)=><button key={`${hit.page}-${index}`} onClick={()=>{navigatePage(hit.page);setSearchOpen(false);}}><FileText size={17}/><span><strong>Страница {hit.page}{hit.clause?` · п. ${hit.clause}`:''}</strong><small>{hit.snippet}</small></span><ChevronRight size={15}/></button>)}{!searchLoading&&!searchError&&searchResults?.total===0&&<p className="muted empty-small">Ничего не найдено.</p>}</div>}</div>}
      <span className="dashboard-topbar-caption">{view==='document'?'ПРОВЕРКА ДОКУМЕНТА':'РАБОЧЕЕ ПРОСТРАНСТВО'}</span>
      <div className="topbar-right"><IconButton label="Обновить данные" onClick={refreshAll}><RefreshCw size={18}/></IconButton><div className="popover-anchor"><button className="profile-button" aria-label="Профиль" aria-expanded={popover==='profile'} onClick={()=>setPopover(popover==='profile'?null:'profile')}><span className="avatar">{user?.initials||'…'}</span><ChevronDown size={15}/></button>{popover==='profile'&&<div className="popover profile-popover"><strong>{user?.fullName||'Профиль недоступен'}</strong><span className="muted">{user?.email}</span><div className="popover-divider"/><button onClick={()=>openModal('info')}><CircleHelp size={17}/>О рабочем пространстве</button></div>}</div></div>
    </header>
    {(view==='project'||view==='document')&&<div className="project-breadcrumb"><button onClick={()=>setView('documents')}><Files size={14}/>Документы</button><ChevronRight size={13}/>{view==='document'?<><button onClick={()=>setView('project')}>{activeProject?.title||'Проект'}</button><ChevronRight size={13}/><span>Просмотр документа</span></>:<span>{activeProject?.title||'Загрузка проекта…'}</span>}</div>}
    {view==='document'&&activeDocument&&<section className="document-heading" aria-label="Текущий документ"><div className="document-icon"><FileText size={29}/><span>{activeDocument.type?.toUpperCase()||'ФАЙЛ'}</span></div><div className="document-heading-text"><span className="analysis-eyebrow">РЕЗУЛЬТАТЫ АНАЛИЗА</span><div className="document-title-line"><h1>{activeDocument.name}</h1></div><p>Страниц: {activeDocument.totalPages} <span>·</span> Проверено правил: {activeDocument.rulesChecked}</p><small>{dateTime(activeDocument.updatedAt||activeDocument.createdAt)} · {activeDocument.label}</small></div><div className="document-actions"><button className="primary-button" disabled={activeDocument.phase!=='ready'||!reportModes.length} onClick={()=>openModal('report')}><Download size={17}/><span>Скачать отчёт</span></button><div className="popover-anchor"><IconButton label="Действия с документом" className="outlined" onClick={()=>setPopover(popover==='document'?null:'document')}><EllipsisVertical size={20}/></IconButton>{popover==='document'&&<div className="popover document-menu"><button onClick={()=>{setDraftName(activeDocument.name);openModal('rename');}}><Pencil size={16}/>Переименовать</button></div>}</div></div></section>}
    </div>
    <main id="main-content" className="main-content" tabIndex={-1}>
      {data.error&&<ErrorNotice message={data.error} onRetry={data.refresh}/>}{actionError&&<ErrorNotice message={actionError}/>}
      {data.loading&&view!=='settings'?<div className="api-state" role="status"><LoaderCircle className="spin"/>Загружаем рабочее пространство…</div>:<>
      {view==='documents'&&(!data.error||projects.length>0)&&<ProjectsView projects={projects} onOpen={openProject} onCreate={()=>openModal('create-project')} query={dashboardQuery} onQueryChange={setDashboardQuery}/>}
      {view==='project'&&(activeProject?<ProjectFilesView key={activeProject.id} project={activeProject} onUpload={uploadFiles} onOpenDocument={openDocument} onStart={startAnalysis} onRerun={rerunProject} analysisModes={analysisModes.config} analysisModesLoading={analysisModes.loading} analysisModesError={analysisModes.error} onRetryAnalysisModes={analysisModes.refresh} selectedAnalysisMode={selectedAnalysisMode} onOpenSettings={()=>setView('settings')}/>:!data.error&&<div className="api-state"><p>Проект не найден или ещё загружается.</p><button className="secondary-button" onClick={data.refresh}>Обновить</button><button onClick={()=>setView('documents')}>К проектам</button></div>)}
      {view==='document'&&<>{live.error&&<ErrorNotice message={live.error} onRetry={live.refresh}/>} {activeDocument?.phase==='ready'&&activeDocument.errorMessage&&<ErrorNotice message={`${live.findings.length?'Повторная проверка не удалась. Показаны предыдущие результаты. ':''}${activeDocument.errorMessage}`}/>} {!activeDocument&&!live.error&&<div className="api-state" role="status"><LoaderCircle className="spin"/>Загружаем документ…</div>}{activeDocument&&(activeDocument.phase==='ready'?<DocumentWorkspace document={activeDocument} pageContent={live.pageContent} outline={live.outline} pageLoading={live.pageLoading} pageError={live.pageError} onRetryPage={live.retryPage} page={page} selected={findingId} search={search} findings={live.findings} statuses={statuses} pendingIds={pendingIds} onPage={navigatePage} onSelect={selectFinding} onStatus={(id,status)=>{void changeStatus(id,status).catch(()=>{});}} rules={rules} onManageRules={()=>setView('rules')} onEditRule={rule=>setRuleDialog({mode:'edit',rule})}/>:<div className="api-state" role="status">{(activeDocument.phase==='processing'||activeDocument.phase==='queued')&&<LoaderCircle className="spin"/>}<h2>{activeDocument.label}</h2><p>{activeDocument.errorMessage||'Результаты появятся после завершения обработки.'}</p><progress value={activeDocument.progress} max={100}/><button className="secondary-button" onClick={live.refresh}>Обновить статус</button></div>)}</>}
      {view==='rules'&&<RulesManager rules={rules} onAdd={()=>setRuleDialog({mode:'create'})} onEdit={rule=>setRuleDialog({mode:'edit',rule})} onDelete={rule=>setRuleDialog({mode:'delete',rule})} onToggle={toggleRule}/>}
      {view==='settings'&&<SettingsView config={analysisModes.config} loading={analysisModes.loading} error={analysisModes.error} selectedMode={selectedAnalysisMode} onChange={analysisModes.selectMode} onRetry={analysisModes.refresh} storageError={analysisModes.storageError}/>}
      {view==='history'&&<section className="secondary-view history-view"><div className="view-title"><div><span className="eyebrow">ЖУРНАЛ ДЕЙСТВИЙ</span><h1>История действий</h1><p>Последние проверки, решения и скачанные отчёты.</p></div><span className="count-chip"><Clock3 size={16}/>Последние 100 событий</span></div>{!history.length?<div className="api-state">Действий пока нет. Создайте проект и загрузите документы.</div>:<ol className="timeline">{history.map((entry,index)=><li key={entry.id}><span className={`timeline-icon ${index===0?'latest':''}`}><History size={18}/></span><div><h3>{entry.title}</h3><p>{entry.detail}</p></div><time dateTime={entry.time}>{dateTime(entry.time)}</time></li>)}</ol>}</section>}
      </>}
    </main>
    <footer className="statusbar"><span><span className="local-indicator"/>{data.error?'Нет связи с API':'Обработка на сервере'}</span><span><ShieldCheck size={13}/>Решения сохраняются в базе данных</span><button onClick={()=>openModal('info')}><CircleHelp size={13}/>Помощь</button></footer>
    {modal==='create-project'&&<NewProjectDialog onCreate={createProject} onClose={()=>setModal(null)}/>}
    {ruleDialog&&ruleDialog.mode!=='delete'&&<RuleEditor rule={ruleDialog.mode==='edit'?ruleDialog.rule:null} categories={categories} onSave={saveRule} onClose={()=>setRuleDialog(null)}/>}
    {ruleDialog?.mode==='delete'&&<DeleteRuleDialog rule={ruleDialog.rule} onConfirm={deleteRule} onClose={()=>setRuleDialog(null)}/>}
    {toast&&<div className="toast" role="status"><span><Check size={16}/></span>{toast}<button aria-label="Скрыть уведомление" onClick={()=>setToast('')}><X size={16}/></button></div>}
    {modal==='rename'&&<Modal title="Переименовать документ" closeDisabled={saving} onClose={()=>setModal(null)}><form onSubmit={renameDocument}><label className="form-label" htmlFor="document-name">Название документа</label><div className="name-input"><input id="document-name" autoFocus required disabled={saving} maxLength={255} value={draftName} onChange={event=>setDraftName(event.target.value)}/></div>{modalError&&<ErrorNotice message={modalError}/>}<div className="modal-actions"><button type="button" className="secondary-button" disabled={saving} onClick={()=>setModal(null)}>Отмена</button><button className="primary-button" disabled={saving||!draftName.trim()}>{saving?'Сохраняем…':'Сохранить'}</button></div></form></Modal>}
    {modal==='report'&&<Modal title="Скачать отчёт" closeDisabled={saving} onClose={()=>setModal(null)}><form onSubmit={exportReport}><label className="form-label" htmlFor="report-mode">Содержание отчёта</label><select id="report-mode" className="form-select" disabled={saving} value={reportMode} onChange={event=>{const value=event.target.value as ReportModeId;setReportMode(value);setReportFormat((reportModes.find(item=>item.id===value)?.formats[0]||'docx') as ReportFormat);}}>{reportModes.map(mode=><option key={mode.id} value={mode.id}>{mode.title}</option>)}</select><p className="report-description">{modeInfo?.description}</p><label className="form-label" htmlFor="report-format">Формат</label><select id="report-format" className="form-select" disabled={saving} value={reportFormat} onChange={event=>setReportFormat(event.target.value as ReportFormat)}>{modeInfo?.formats.map(format=><option key={format} value={format}>{format.toUpperCase()}</option>)}</select><label className="report-option"><input type="checkbox" disabled={saving} checked={includeDismissed} onChange={event=>setIncludeDismissed(event.target.checked)}/>Включить отклонённые замечания</label>{modalError&&<ErrorNotice message={modalError}/>}<div className="modal-actions"><button type="button" className="secondary-button" disabled={saving} onClick={()=>setModal(null)}>Отмена</button><button className="primary-button" disabled={saving||!modeInfo}>{saving?'Формируем отчёт…':'Скачать'}</button></div></form></Modal>}
    {modal==='info'&&<Modal title="О рабочем пространстве" onClose={()=>setModal(null)}><div className="info-content"><p>Создайте проект, загрузите документы, нажмите «Начать анализ» и дождитесь завершения проверки. Файлы и решения по замечаниям сохраняются на сервере.</p><p>Откройте документ, чтобы сопоставить замечания с исходным текстом, принять или отклонить их и скачать отчёт. Поиск работает по всем страницам.</p><p>Для документов из ZIP доступен отдельный просмотр. Повторная проверка использует текущие включённые правила. Источник каждого результата указан в подробностях замечания.</p><p>Текущий профиль предоставляется API; вход и управление доступом в этой версии не реализованы.</p></div><div className="modal-actions"><button className="primary-button" onClick={()=>setModal(null)}>Понятно</button></div></Modal>}
  </div>;
  return <div className={`dashboard-canvas${view==='document'?' analysis-canvas':''}`}>{shell}</div>;
}
