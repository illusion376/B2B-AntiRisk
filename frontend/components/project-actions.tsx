'use client';

import { useRef, useState } from 'react';
import { LoaderCircle, Pencil, Trash2 } from 'lucide-react';
import { errorMessage } from '@/lib/api';
import type { Project } from '@/lib/types';
import { Modal } from './ui';

export function ProjectActions({ project, onRename, onDelete, compact = false, disabled = false }: {
  project: Project;
  onRename: (project: Project) => void;
  onDelete: (project: Project) => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  return <div className="project-actions" role="group" aria-label={`Действия с проектом «${project.title}»`}>
    <button type="button" className={compact ? 'dashboard-row-action' : 'secondary-button'} title="Переименовать проект"
      aria-label={`Переименовать проект «${project.title}»`} disabled={disabled} onClick={() => onRename(project)}>
      <Pencil size={15} />{!compact && 'Переименовать'}
    </button>
    <button type="button" className={`${compact ? 'dashboard-row-action' : 'secondary-button'} project-delete-action`} title="Удалить проект"
      aria-label={`Удалить проект «${project.title}»`} disabled={disabled} onClick={() => onDelete(project)}>
      <Trash2 size={15} />{!compact && 'Удалить'}
    </button>
  </div>;
}

export function ProjectActionDialog({ project, mode, onConfirm, onClose }: {
  project: Project;
  mode: 'rename' | 'delete';
  onConfirm: (title: string) => Promise<void>;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(project.title);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const lock = useRef(false);
  const deleting = mode === 'delete';

  async function submit() {
    if (lock.current || (!deleting && !title.trim())) return;
    lock.current = true;
    setSaving(true);
    setError('');
    try {
      await onConfirm(title.trim());
      onClose();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      lock.current = false;
      setSaving(false);
    }
  }

  return <Modal title={deleting ? 'Удалить проект?' : 'Переименовать проект'}
    onClose={() => { if (!lock.current) onClose(); }} closeDisabled={saving}>
    <form aria-busy={saving} onSubmit={event => { event.preventDefault(); void submit(); }}>
      {deleting ? <div className="project-delete-warning">
        <p>Проект «<strong>{project.title}</strong>» будет удалён вместе со всеми файлами и результатами проверок.</p>
        <p>Загрузок в проекте: {project.files.length}. Отменить удаление нельзя.</p>
      </div> : <>
        <label className="form-label" htmlFor="rename-project-title">Название проекта</label>
        <input id="rename-project-title" className="form-input" autoFocus required maxLength={120} disabled={saving}
          value={title} aria-invalid={!!error} aria-describedby={error ? 'project-action-error' : undefined}
          onChange={event => { setTitle(event.target.value); setError(''); }} />
      </>}
      {error && <p id="project-action-error" className="field-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="secondary-button" autoFocus={deleting} disabled={saving} onClick={onClose}>Отмена</button>
        <button type="submit" className={`primary-button${deleting ? ' project-delete-confirm' : ''}`}
          disabled={saving || (!deleting && (!title.trim() || title.trim() === project.title))}>
          {saving ? <LoaderCircle size={16} className="spin" /> : deleting ? <Trash2 size={16} /> : <Pencil size={16} />}
          {saving ? deleting ? 'Удаляем…' : 'Сохраняем…' : deleting ? 'Удалить проект' : 'Сохранить'}
        </button>
      </div>
    </form>
  </Modal>;
}
