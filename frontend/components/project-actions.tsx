'use client';

import { useRef, useState } from 'react';
import { LoaderCircle, Pencil, Trash2 } from 'lucide-react';
import { errorMessage } from '@/lib/api';
import type { Project } from '@/lib/types';
import { Modal } from './ui';

interface ProjectActionsProps {
  project: Project;
  onRename: (project: Project) => void;
  onDelete: (project: Project) => void;
  compact?: boolean;
  disabled?: boolean;
}

export function ProjectActions({ project, onRename, onDelete, compact = false, disabled = false }: ProjectActionsProps) {
  return <div className="project-actions">
    <button type="button" className={compact ? 'dashboard-row-action' : 'secondary-button'} disabled={disabled}
      aria-label={compact ? `Переименовать проект «${project.title}»` : undefined} title="Переименовать проект" onClick={() => onRename(project)}>
      <Pencil size={16} />{!compact && 'Переименовать'}
    </button>
    <button type="button" className={`${compact ? 'dashboard-row-action' : 'secondary-button'} project-delete-action`} disabled={disabled}
      aria-label={compact ? `Удалить проект «${project.title}»` : undefined} title="Удалить проект" onClick={() => onDelete(project)}>
      <Trash2 size={16} />{!compact && 'Удалить'}
    </button>
  </div>;
}

interface ProjectActionDialogProps {
  project: Project;
  mode: 'rename' | 'delete';
  onConfirm: (title: string) => Promise<void>;
  onClose: () => void;
}

export function ProjectActionDialog({ project, mode, onConfirm, onClose }: ProjectActionDialogProps) {
  const [title, setTitle] = useState(project.title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const saveLock = useRef(false);
  const close = () => { if (!saveLock.current) onClose(); };

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saveLock.current || (mode === 'rename' && !title.trim())) return;
    saveLock.current = true;
    setSaving(true);
    setError('');
    try {
      await onConfirm(title.trim());
      onClose();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }

  return <Modal title={mode === 'rename' ? 'Переименовать проект' : 'Точно удалить проект?'} closeDisabled={saving} onClose={close}>
    <form onSubmit={submit}>
      {mode === 'rename' ? <>
        <label className="form-label" htmlFor="project-title">Название проекта</label>
        <input id="project-title" className="form-input" required autoFocus maxLength={120} disabled={saving} value={title} onChange={event => setTitle(event.target.value)} />
      </> : <div className="project-delete-warning">
        <p>Проект «{project.title}», его документы и результаты проверки будут удалены.</p>
      </div>}
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="secondary-button" disabled={saving} onClick={close}>Отмена</button>
        <button className={`primary-button${mode === 'delete' ? ' project-delete-confirm' : ''}`} disabled={saving || (mode === 'rename' && !title.trim())}>
          {saving && <LoaderCircle size={15} className="spin" />}{saving ? 'Сохраняем…' : mode === 'rename' ? 'Сохранить' : 'Удалить проект'}
        </button>
      </div>
    </form>
  </Modal>;
}
