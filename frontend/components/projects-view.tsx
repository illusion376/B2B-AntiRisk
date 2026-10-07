'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowDownWideNarrow, ArrowUpRight, ChevronLeft, ChevronRight, FileText, FolderOpen, Plus } from 'lucide-react';
import type { Project, ProjectDraft } from '@/lib/types';
import { DEMO_PROJECT_ID, formatProjectDate, getProcessing } from '@/lib/projects';
import { Modal } from './ui';
import { useProcessingClock } from './use-processing-clock';

interface ProjectsViewProps {
  projects: Project[];
  onOpen: (project: Project) => void;
  onCreate: () => void;
  riskCount: number;
  checkedCount: number;
  query: string;
  onQueryChange: (query: string) => void;
}

type ProjectFilter = 'all' | 'processing' | 'ready' | 'empty';
const PAGE_SIZE = 8;

export function ProjectsView({ projects,onOpen,onCreate,riskCount,checkedCount,query,onQueryChange }: ProjectsViewProps) {
  const [sort,setSort] = useState('recent');
  const [filter,setFilter] = useState<ProjectFilter>('all');
  const [page,setPage] = useState(0);
  const files = useMemo(()=>projects.flatMap(project=>project.files),[projects]);
  const now = useProcessingClock(files);
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const projectState = (project:Project): Exclude<ProjectFilter,'all'> => !project.files.length ? 'empty' : project.files.some(file=>getProcessing(file,now).phase!=='ready') ? 'processing' : 'ready';
  const filtered = projects.filter(project=>(filter==='all' || projectState(project)===filter) && [project.title,project.description,...project.files.map(file=>file.name)].join(' ').toLocaleLowerCase('ru').includes(normalizedQuery)).sort((a,b)=>sort==='recent'?b.updatedAt-a.updatedAt:a.title.localeCompare(b.title,'ru',{numeric:true}));
  const pageCount = Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));
  const currentPage = Math.min(page,pageCount-1);
  const visible = filtered.slice(currentPage*PAGE_SIZE,(currentPage+1)*PAGE_SIZE);
  useEffect(()=>setPage(0),[query,filter,sort]);
  const filters: {id:ProjectFilter;label:string;count:number}[] = [
    {id:'all',label:'Все проекты',count:projects.length},
    {id:'processing',label:'В обработке',count:projects.filter(project=>projectState(project)==='processing').length},
    {id:'ready',label:'Готовые',count:projects.filter(project=>projectState(project)==='ready').length},
    {id:'empty',label:'Без файлов',count:projects.filter(project=>projectState(project)==='empty').length},
  ];

  return <section className="secondary-view projects-view">
    <div className="view-title"><div><span className="eyebrow">ОБЗОР / ДОКУМЕНТЫ</span><h1>Рабочее пространство</h1><p>Проекты, документы и проверка рисков — в одном месте.</p></div><button className="primary-button" onClick={onCreate}><Plus size={16}/>Новый проект</button></div>
    <div className="dashboard-list-toolbar"><div className="dashboard-filter-tabs" role="group" aria-label="Фильтр проектов по статусу">{filters.map(item=><button key={item.id} aria-pressed={filter===item.id} onClick={()=>setFilter(item.id)}>{item.label}<span>{item.count}</span></button>)}</div><label className="dashboard-sort"><ArrowDownWideNarrow size={14}/><span className="sr-only">Сортировка проектов</span><select value={sort} onChange={event=>setSort(event.target.value)}><option value="recent">Сначала новые</option><option value="name">По названию</option></select></label></div>
    {normalizedQuery && <p className="dashboard-search-result" role="status">По запросу «{query.trim()}» найдено: {filtered.length}<button onClick={()=>onQueryChange('')}>Сбросить поиск</button></p>}
    {filtered.length ? <><div className="dashboard-table-scroll"><table className="dashboard-project-table"><thead><tr><th scope="col">Проект</th><th scope="col">Статус</th><th scope="col">Файлы</th><th scope="col">Замечания</th><th scope="col">Обновлён</th><th scope="col"><span className="sr-only">Открыть</span></th></tr></thead><tbody>{visible.map(project=>{
      const state=projectState(project);
      const isDemo=project.id===DEMO_PROJECT_ID;
      return <tr key={project.id}><td><button className="dashboard-project-name" onClick={()=>onOpen(project)}><span className="dashboard-file-symbol"><FolderOpen size={17}/></span><span><strong>{project.title}</strong><small>{project.description || 'Документы проекта'}</small></span></button></td><td><span className={`dashboard-state ${state}`}><i/>{state==='processing'?'В обработке':state==='empty'?'Ожидает файлов':isDemo?'Демопроект':'Готово · демо'}</span></td><td><span className="dashboard-file-count"><FileText size={13}/>{project.files.length}</span></td><td><span className={isDemo && checkedCount && riskCount?'dashboard-risk-value':''}>{isDemo && checkedCount?riskCount:'—'}</span></td><td><time dateTime={new Date(project.updatedAt).toISOString()}>{formatProjectDate(project.updatedAt)}</time></td><td><button className="dashboard-row-action" aria-label={`Открыть проект «${project.title}»`} onClick={()=>onOpen(project)}><ArrowUpRight size={16}/></button></td></tr>;
    })}</tbody></table></div><div className="dashboard-table-footer"><span>{currentPage*PAGE_SIZE+1}–{Math.min((currentPage+1)*PAGE_SIZE,filtered.length)} из {filtered.length} проектов</span><nav aria-label="Страницы списка проектов"><button aria-label="Предыдущая страница" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}><ChevronLeft size={15}/></button><span aria-current="page">{currentPage+1}</span><small>/ {pageCount}</small><button aria-label="Следующая страница" disabled={currentPage+1>=pageCount} onClick={()=>setPage(currentPage+1)}><ChevronRight size={15}/></button></nav></div></> : <div className="empty-state dashboard-empty"><FolderOpen size={29}/><h3>Проекты не найдены</h3><p>Измените поисковый запрос или выбранный статус.</p><button className="secondary-button" onClick={()=>{onQueryChange('');setFilter('all');}}>Сбросить фильтры</button></div>}
    <div className="dashboard-list-note"><span className="workspace-online-dot"/>Изменения сохраняются в этом браузере<span>PDF / TXT / ZIP</span></div>
  </section>;
}

interface NewProjectDialogProps {
  onCreate: (draft: ProjectDraft) => string | void;
  onClose: () => void;
}

export function NewProjectDialog({ onCreate, onClose }: NewProjectDialogProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');

  return (
    <Modal title="Новый проект" onClose={onClose}>
      <form onSubmit={event => {
        event.preventDefault();
        if (!title.trim()) return;
        const message = onCreate({ title: title.trim(), description: description.trim() });
        if (message) setError(message);
      }}>
        <label className="form-label" htmlFor="project-title">Название проекта <span aria-hidden="true">*</span></label>
        <input
          id="project-title"
          className="form-input"
          autoFocus
          required
          maxLength={120}
          placeholder="Например, договор поставки"
          value={title}
          aria-invalid={!!error}
          aria-describedby={error ? 'project-error' : undefined}
          onChange={event => {
            setTitle(event.target.value);
            setError('');
          }}
        />
        <label className="form-label" htmlFor="project-description">Описание</label>
        <textarea
          id="project-description"
          className="form-input"
          rows={3}
          maxLength={1000}
          placeholder="О чём этот проект"
          value={description}
          onChange={event => setDescription(event.target.value)}
        />
        <p className="form-hint">После создания можно добавить файлы PDF, TXT и ZIP.</p>
        {error && <p className="field-error" id="project-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Отмена</button>
          <button className="primary-button" disabled={!title.trim()}><Plus size={16} />Создать проект</button>
        </div>
      </form>
    </Modal>
  );
}
