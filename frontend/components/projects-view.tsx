'use client';

import { useMemo, useState } from 'react';
import { FileText, FolderOpen, LoaderCircle, Plus, Search } from 'lucide-react';
import type { Project, ProjectDraft } from '@/lib/types';
import { DEMO_PROJECT_ID, formatProjectDate, getProcessing } from '@/lib/projects';
import { Modal } from './ui';
import { useProcessingClock } from './use-processing-clock';

export function ProjectsView({projects,onOpen,onCreate,riskCount}: {projects:Project[];onOpen:(project:Project)=>void;onCreate:()=>void;riskCount:number}) {
  const [query,setQuery] = useState('');
  const files = useMemo(()=>projects.flatMap(project=>project.files),[projects]);
  const now = useProcessingClock(files);
  const filtered = projects.filter(project => `${project.title} ${project.files.map(file=>file.name).join(' ')}`.toLocaleLowerCase('ru').includes(query.trim().toLocaleLowerCase('ru')));
  return <section className="secondary-view projects-view">
    <div className="view-title"><div><span className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Документы</h1><p>Все проекты и результаты проверки в одном месте.</p></div><button className="primary-button" onClick={onCreate}><Plus size={18} />Новый проект</button></div>
    <div className="projects-toolbar"><h2>Все проекты <span>{projects.length}</span></h2><label className="field-search"><Search size={18} /><input aria-label="Поиск проектов" placeholder="Найти проект или документ..." value={query} onChange={e=>setQuery(e.target.value)} /></label></div>
    <div className="projects-grid">{filtered.map(project => {
      const pending = project.files.filter(file=>getProcessing(file,now).phase!=='ready').length;
      const first = project.files[0];
      return <button key={project.id} className="project-card" onClick={()=>onOpen(project)} aria-label={`Открыть проект «${project.title}»`}>
        <div className="project-card-top"><span className="project-folder"><FolderOpen size={26} strokeWidth={1.6} /></span><span className="project-type">{project.id===DEMO_PROJECT_ID?'Демонстрационный проект':'Проект'}</span></div>
        <h3>{project.title}</h3><p>{project.description || 'Добавьте документы для проверки.'}</p>
        <div className="project-document"><FileText size={20} /><span><strong>{first?.name ?? 'Пока нет документов'}</strong><small>{first ? `Файлов в проекте: ${project.files.length}` : 'PDF, TXT или ZIP'}</small></span></div>
        <div className="project-card-footer"><span className={pending?'project-processing':project.id===DEMO_PROJECT_ID?'project-risk':'project-neutral'}>{pending ? <><LoaderCircle size={13} className="spin" />В обработке: {pending}</> : project.id===DEMO_PROJECT_ID ? (riskCount ? `Замечаний: ${riskCount}` : 'Без замечаний') : first ? 'Обработано · демо' : 'Ожидает файлов'}</span><time dateTime={new Date(project.updatedAt).toISOString()}>{formatProjectDate(project.updatedAt)}</time></div>
      </button>;
    })}</div>
    {!filtered.length && <div className="empty-state"><FolderOpen size={34} /><h3>Проекты не найдены</h3><p>Попробуйте другое название.</p><button className="secondary-button" onClick={()=>setQuery('')}>Сбросить поиск</button></div>}
  </section>;
}

export function NewProjectDialog({onCreate,onClose}: {onCreate:(draft:ProjectDraft)=>string|void;onClose:()=>void}) {
  const [title,setTitle] = useState('');
  const [description,setDescription] = useState('');
  const [error,setError] = useState('');
  return <Modal title="Новый проект" onClose={onClose}><form onSubmit={event=>{event.preventDefault();if(!title.trim())return;const message=onCreate({title:title.trim(),description:description.trim()});if(message)setError(message);}}>
    <label className="form-label" htmlFor="project-title">Название проекта <span aria-hidden="true">*</span></label><input id="project-title" className="form-input" autoFocus required maxLength={120} placeholder="Например, договор поставки" value={title} aria-invalid={!!error} aria-describedby={error?'project-error':undefined} onChange={event=>{setTitle(event.target.value);setError('');}} />
    <label className="form-label" htmlFor="project-description">Описание</label><textarea id="project-description" className="form-input" rows={3} maxLength={1000} placeholder="О чём этот проект" value={description} onChange={event=>setDescription(event.target.value)} />
    <p className="form-hint">После создания можно добавить файлы PDF, TXT и ZIP.</p>
    {error && <p className="field-error" id="project-error" role="alert">{error}</p>}
    <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Отмена</button><button className="primary-button" disabled={!title.trim()}><Plus size={16} />Создать проект</button></div>
  </form></Modal>;
}
