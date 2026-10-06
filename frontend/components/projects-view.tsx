'use client';

import { useMemo, useState } from 'react';
import {
  ArrowDownWideNarrow,
  ArrowUpRight,
  FileText,
  FolderOpen,
  LoaderCircle,
  Plus,
  Search,
  ShieldAlert,
  X,
} from 'lucide-react';
import type { Project, ProjectDraft } from '@/lib/types';
import { DEMO_PROJECT_ID, formatProjectDate, getProcessing } from '@/lib/projects';
import { Modal } from './ui';
import { useProcessingClock } from './use-processing-clock';
import './project-enhancements.css';

interface ProjectsViewProps {
  projects: Project[];
  onOpen: (project: Project) => void;
  onCreate: () => void;
  riskCount: number;
  checkedCount: number;
}

type ProjectSort = 'recent' | 'name';

export function ProjectsView({
  projects,
  onOpen,
  onCreate,
  riskCount,
  checkedCount,
}: ProjectsViewProps) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<ProjectSort>('recent');
  const files = useMemo(() => projects.flatMap(project => project.files), [projects]);
  const now = useProcessingClock(files);
  const pendingCount = files.filter(file => getProcessing(file, now).phase !== 'ready').length;
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const filtered = projects
    .filter(project => [project.title, project.description, ...project.files.map(file => file.name)]
      .join(' ')
      .toLocaleLowerCase('ru')
      .includes(normalizedQuery))
    .sort((left, right) => sort === 'recent'
      ? right.updatedAt - left.updatedAt
      : left.title.localeCompare(right.title, 'ru', { numeric: true }));

  return (
    <section className="secondary-view projects-view">
      <div className="view-title">
        <div>
          <span className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span>
          <h1>Документы</h1>
          <p>Все проекты и результаты проверки в одном месте.</p>
        </div>
        <button className="primary-button" onClick={onCreate}>
          <Plus size={18} />Новый проект
        </button>
      </div>

      <dl className="workspace-summary" aria-label="Сводка рабочего пространства">
        <div className="workspace-summary-card">
          <dt><span className="summary-icon"><FolderOpen size={19} /></span>Проекты</dt>
          <dd>{projects.length}</dd>
          <dd className="summary-caption">В рабочем пространстве</dd>
        </div>
        <div className="workspace-summary-card">
          <dt><span className="summary-icon"><FileText size={19} /></span>Документы</dt>
          <dd>{files.length}</dd>
          <dd className="summary-caption">Во всех проектах</dd>
        </div>
        <div className={`workspace-summary-card ${pendingCount ? 'summary-processing' : ''}`}>
          <dt><span className="summary-icon"><LoaderCircle size={19} className={pendingCount ? 'spin' : ''} /></span>В обработке</dt>
          <dd>{pendingCount}</dd>
          <dd className="summary-caption">{pendingCount ? 'Демонстрационная обработка' : 'Нет файлов в очереди'}</dd>
        </div>
        <div className={`workspace-summary-card ${checkedCount && riskCount ? 'summary-attention' : ''}`}>
          <dt><span className="summary-icon"><ShieldAlert size={19} /></span>Замечания</dt>
          <dd>{checkedCount ? riskCount : '—'}</dd>
          <dd className="summary-caption">{checkedCount ? 'В демонстрационном документе' : 'Нет результатов проверки'}</dd>
        </div>
      </dl>

      <div className="projects-toolbar">
        <div className="projects-toolbar-title">
          <h2>Все проекты <span>{projects.length}</span></h2>
          <p>Выберите проект, чтобы продолжить работу</p>
        </div>
        <div className="project-list-controls">
          <div className="field-search project-search">
            <Search size={17} aria-hidden="true" />
            <input
              aria-label="Поиск по названию, описанию проекта или документу"
              placeholder="Найти проект или документ"
              value={query}
              onChange={event => setQuery(event.target.value)}
            />
            {query && (
              <button type="button" className="search-clear" aria-label="Очистить поиск проектов" onClick={() => setQuery('')}>
                <X size={16} />
              </button>
            )}
          </div>
          <label className="project-sort">
            <ArrowDownWideNarrow size={17} aria-hidden="true" />
            <span className="sr-only">Сортировка проектов</span>
            <select value={sort} onChange={event => setSort(event.target.value as ProjectSort)}>
              <option value="recent">Сначала новые</option>
              <option value="name">По названию</option>
            </select>
          </label>
        </div>
      </div>

      {normalizedQuery && (
        <p className="project-search-result" role="status">Найдено проектов: {filtered.length} из {projects.length}</p>
      )}

      {filtered.length > 0 ? (
        <div className="projects-grid">
          {filtered.map(project => {
            const pending = project.files.filter(file => getProcessing(file, now).phase !== 'ready').length;
            const first = project.files[0];
            const isDemo = project.id === DEMO_PROJECT_ID;

            return (
              <button key={project.id} className="project-card" onClick={() => onOpen(project)} aria-label={`Открыть проект «${project.title}»`}>
                <div className="project-card-top">
                  <span className="project-folder"><FolderOpen size={26} strokeWidth={1.6} /></span>
                  <span className="project-type">{isDemo ? 'Демопроект' : 'Проект'}</span>
                  <ArrowUpRight size={18} className="project-card-arrow" aria-hidden="true" />
                </div>
                <h3>{project.title}</h3>
                <p>{project.description || 'Добавьте документы для проверки.'}</p>
                <div className="project-document">
                  <FileText size={20} />
                  <span>
                    <strong>{first?.name ?? 'Пока нет документов'}</strong>
                    <small>{first ? `Файлов в проекте: ${project.files.length}` : 'PDF, TXT или ZIP'}</small>
                  </span>
                </div>
                <div className="project-card-footer">
                  <span className={pending ? 'project-processing' : isDemo && checkedCount && riskCount ? 'project-risk' : 'project-neutral'}>
                    {pending ? (
                      <><LoaderCircle size={13} className="spin" />В обработке: {pending}</>
                    ) : isDemo ? (
                      !checkedCount ? 'Нет результатов проверки' : riskCount ? `Замечаний: ${riskCount}` : 'Без замечаний'
                    ) : first ? 'Обработано · демо' : 'Ожидает файлов'}
                  </span>
                  <time dateTime={new Date(project.updatedAt).toISOString()} title="Последнее обновление проекта">
                    {formatProjectDate(project.updatedAt)}
                  </time>
                </div>
              </button>
            );
          })}
          {!normalizedQuery && (
            <button className="project-create-card" onClick={onCreate}>
              <span><Plus size={25} strokeWidth={1.5} /></span>
              <strong>Новый проект</strong>
              <p>Соберите документы одной сделки<br />и работайте с ними в одном месте</p>
            </button>
          )}
        </div>
      ) : (
        <div className="empty-state projects-empty-state">
          <span className="project-empty-icon"><FolderOpen size={32} strokeWidth={1.5} /></span>
          <h3>{projects.length ? 'По вашему запросу ничего не найдено' : 'Начните с первого проекта'}</h3>
          <p>{projects.length
            ? 'Попробуйте другое название, описание или имя документа.'
            : 'Создайте проект и добавьте документы, с которыми хотите работать.'}</p>
          {projects.length ? (
            <button className="secondary-button" onClick={() => setQuery('')}>Сбросить поиск</button>
          ) : (
            <button className="primary-button" onClick={onCreate}><Plus size={17} />Создать проект</button>
          )}
        </div>
      )}
    </section>
  );
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
