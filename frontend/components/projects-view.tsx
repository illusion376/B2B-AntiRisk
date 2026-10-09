'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowDownWideNarrow, ArrowUpRight, ChevronLeft, ChevronRight, FileText, FolderOpen, LoaderCircle, Plus } from 'lucide-react';
import type { Project, ProjectDraft } from '@/lib/types';
import { formatProjectDate } from '@/lib/projects';
import { Modal } from './ui';
import { UnknownResultsBadge } from './shared-badges';
import './project-enhancements.css';

interface ProjectsViewProps {
  projects: Project[];
  onOpen: (project: Project) => void;
  onCreate: () => void;
  query: string;
  onQueryChange: (query: string) => void;
}

type ProjectFilter = 'all' | 'uploaded' | 'processing' | 'ready' | 'failed' | 'empty';
const PAGE_SIZE = 8;

function projectState(project: Project): Exclude<ProjectFilter, 'all'> {
  if (!project.files.length) return 'empty';
  if (project.processingCount > 0 || project.files.some(file => file.phase === 'queued' || file.phase === 'processing'
    || file.documents.some(document => document.phase === 'queued' || document.phase === 'processing'))) return 'processing';
  if (project.files.some(file => file.phase === 'uploaded'
    || file.documents.some(document => document.phase === 'uploaded'))) return 'uploaded';
  if (project.files.some(file => file.phase === 'failed' || file.phase === 'unsupported'
    || file.documents.some(document => document.phase === 'failed' || document.phase === 'unsupported'))) return 'failed';
  return 'ready';
}

const projectStateLabels = {
  uploaded: 'Ожидает запуска',
  processing: 'В обработке',
  ready: 'Готово',
  failed: 'С ошибками',
  empty: 'Ожидает файлов',
};

export function ProjectsView({ projects, onOpen, onCreate, query, onQueryChange }: ProjectsViewProps) {
  const [sort, setSort] = useState('recent');
  const [filter, setFilter] = useState<ProjectFilter>('all');
  const [page, setPage] = useState(0);
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const filtered = projects.filter(project => {
    const searchText = [project.title, project.description, ...project.files.flatMap(file => [
      file.name, ...file.documents.flatMap(document => [document.name, document.relativePath ?? '']),
    ])].join(' ').toLocaleLowerCase('ru');
    return (filter === 'all' || projectState(project) === filter) && searchText.includes(normalizedQuery);
  }).sort((left, right) => sort === 'recent'
    ? right.updatedAt - left.updatedAt
    : left.title.localeCompare(right.title, 'ru', { numeric: true }));
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  useEffect(() => setPage(0), [query, filter, sort]);

  const filters: { id: ProjectFilter; label: string; count: number }[] = [
    { id: 'all', label: 'Все проекты', count: projects.length },
    { id: 'uploaded', label: 'Ожидают запуска', count: projects.filter(project => projectState(project) === 'uploaded').length },
    { id: 'processing', label: 'В обработке', count: projects.filter(project => projectState(project) === 'processing').length },
    { id: 'ready', label: 'Готовые', count: projects.filter(project => projectState(project) === 'ready').length },
    { id: 'failed', label: 'С ошибками', count: projects.filter(project => projectState(project) === 'failed').length },
    { id: 'empty', label: 'Без файлов', count: projects.filter(project => projectState(project) === 'empty').length },
  ];

  return (
    <section className="secondary-view projects-view">
      <div className="view-title">
        <div>
          <span className="eyebrow">ОБЗОР / ДОКУМЕНТЫ</span>
          <h1>Рабочее пространство</h1>
          <p>Проекты, документы и проверка рисков — в одном месте.</p>
        </div>
        <button className="primary-button" onClick={onCreate}><Plus size={16} />Новый проект</button>
      </div>
      <div className="dashboard-list-toolbar">
        <div className="dashboard-filter-tabs" role="group" aria-label="Фильтр проектов по статусу">
          {filters.map(item => (
            <button key={item.id} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
              {item.label}<span>{item.count}</span>
            </button>
          ))}
        </div>
        <label className="dashboard-sort">
          <ArrowDownWideNarrow size={14} />
          <span className="sr-only">Сортировка проектов</span>
          <select value={sort} onChange={event => setSort(event.target.value)}>
            <option value="recent">Сначала новые</option>
            <option value="name">По названию</option>
          </select>
        </label>
      </div>
      {normalizedQuery && (
        <p className="dashboard-search-result" role="status">
          По запросу «{query.trim()}» найдено: {filtered.length}
          <button onClick={() => onQueryChange('')}>Сбросить поиск</button>
        </p>
      )}
      {filtered.length > 0 ? (
        <>
          <div className="dashboard-table-scroll">
            <table className="dashboard-project-table">
              <thead>
                <tr>
                  <th scope="col">Проект</th><th scope="col">Статус</th><th scope="col">Файлы</th>
                  <th scope="col">Замечания</th><th scope="col">Обновлён</th>
                  <th scope="col"><span className="sr-only">Открыть</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map(project => {
                  const state = projectState(project);
                  const riskCount = project.counts.critical + project.counts.warning + project.counts.low;
                  const hasResults = riskCount > 0 || project.counts.ok > 0 || project.counts.unknown > 0 || project.files.some(file => file.rulesChecked > 0);
                  return (
                    <tr key={project.id}>
                      <td>
                        <button className="dashboard-project-name" onClick={() => onOpen(project)}>
                          <span className="dashboard-file-symbol"><FolderOpen size={17} /></span>
                          <span><strong>{project.title}</strong><small>{project.description || 'Документы проекта'}</small></span>
                        </button>
                      </td>
                      <td><span className={`dashboard-state ${state}`}><i />{projectStateLabels[state]}</span></td>
                      <td><span className="dashboard-file-count"><FileText size={13} />{project.files.length}</span></td>
                      <td>
                        <span className={riskCount ? 'dashboard-risk-value' : ''} title={hasResults ? 'Замечания по результатам проверки документов проекта' : 'Нет результатов проверки'}>
                          {hasResults ? riskCount : '—'}
                        </span>
                        <UnknownResultsBadge count={project.counts.unknown} />
                      </td>
                      <td><time dateTime={new Date(project.updatedAt).toISOString()}>{formatProjectDate(project.updatedAt)}</time></td>
                      <td>
                        <button className="dashboard-row-action" aria-label={`Открыть проект «${project.title}»`} onClick={() => onOpen(project)}>
                          <ArrowUpRight size={16} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="dashboard-table-footer">
            <span>{currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} из {filtered.length} проектов</span>
            <nav aria-label="Страницы списка проектов">
              <button aria-label="Предыдущая страница" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={15} /></button>
              <span aria-current="page">{currentPage + 1}</span><small>/ {pageCount}</small>
              <button aria-label="Следующая страница" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={15} /></button>
            </nav>
          </div>
        </>
      ) : (
        <div className="empty-state dashboard-empty">
          <FolderOpen size={29} />
          <h3>{projects.length ? 'Проекты не найдены' : 'Создайте первый проект'}</h3>
          <p>{projects.length ? 'Измените поисковый запрос или выбранный статус.' : 'Добавьте документы одной сделки, чтобы начать проверку.'}</p>
          {projects.length ? (
            <button className="secondary-button" onClick={() => { onQueryChange(''); setFilter('all'); }}>Сбросить фильтры</button>
          ) : <button className="primary-button" onClick={onCreate}><Plus size={16} />Новый проект</button>}
        </div>
      )}
      <div className="dashboard-list-note">
        <span className="workspace-online-dot" />Проекты и результаты сохраняются на сервере
      </div>
    </section>
  );
}

interface NewProjectDialogProps {
  onCreate: (draft: ProjectDraft) => Promise<string | void>;
  onClose: () => void;
}

export function NewProjectDialog({ onCreate, onClose }: NewProjectDialogProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const saveLock = useRef(false);

  async function createProject() {
    if (!title.trim() || saveLock.current) return;
    saveLock.current = true;
    setSaving(true);
    setError('');
    try {
      const message = await onCreate({ title: title.trim(), description: description.trim() });
      if (message) setError(message);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось создать проект. Попробуйте ещё раз.');
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }

  return (
    <Modal title="Новый проект" onClose={() => { if (!saveLock.current) onClose(); }} closeDisabled={saving}>
      <form aria-busy={saving} onSubmit={event => { event.preventDefault(); void createProject(); }}>
        <label className="form-label" htmlFor="project-title">Название проекта <span aria-hidden="true">*</span></label>
        <input
          id="project-title" className="form-input" autoFocus required maxLength={120} disabled={saving}
          placeholder="Например, договор поставки" value={title} aria-invalid={!!error}
          aria-describedby={error ? 'project-error' : undefined}
          onChange={event => { setTitle(event.target.value); setError(''); }}
        />
        <label className="form-label" htmlFor="project-description">Описание</label>
        <textarea
          id="project-description" className="form-input" rows={3} maxLength={1000} disabled={saving}
          placeholder="О чём этот проект" value={description} onChange={event => setDescription(event.target.value)}
        />
        <p className="form-hint">После создания можно добавить документы, изображения или ZIP-архив.</p>
        {error && <p className="field-error" id="project-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="secondary-button" disabled={saving} onClick={onClose}>Отмена</button>
          <button className="primary-button" disabled={saving || !title.trim()}>
            {saving ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />}
            {saving ? 'Создаём проект…' : 'Создать проект'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
