'use client';

import { Fragment, useRef, useState } from 'react';
import { AlertCircle, Archive, ArrowDownWideNarrow, ArrowUpRight, Check, Clock3, FileText, LoaderCircle, Play, RotateCw, Search, Trash2, UploadCloud, X } from 'lucide-react';
import { errorMessage } from '@/lib/api';
import type { AnalysisMode, AnalysisModes, DocumentInfo, ProcessingState, Project, ProjectFile, SeverityCounts } from '@/lib/types';
import { formatFileSize, formatProjectDate, MAX_FILE_BYTES, UPLOAD_ACCEPT } from '@/lib/projects';
import { Modal } from './ui';
import './project-enhancements.css';

interface ProjectFilesViewProps {
  project: Project;
  onUpload: (files: File[]) => Promise<string[]>;
  onOpenDocument: (document: DocumentInfo) => void;
  onStart: (mode: AnalysisMode) => Promise<void>;
  onRerun?: (mode: AnalysisMode) => Promise<void>;
  analysisModes: AnalysisModes | null;
  analysisModesLoading: boolean;
  analysisModesError: string | null;
  onRetryAnalysisModes: () => void;
  selectedAnalysisMode: AnalysisMode | null;
  onOpenSettings: () => void;
  onRemoveFile: (file: ProjectFile) => Promise<void>;
}

type FileStatusFilter = 'all' | 'uploaded' | 'processing' | 'ready' | 'failed';
const isPending = (item: ProcessingState) => item.phase === 'queued' || item.phase === 'processing';
const hasError = (item: ProcessingState) => item.phase === 'failed' || item.phase === 'unsupported';
const riskCount = (counts: SeverityCounts) => counts.critical + counts.warning + counts.low;

function fileState(file: ProjectFile): Exclude<FileStatusFilter, 'all'> {
  if (isPending(file) || file.documents.some(isPending)) return 'processing';
  if (file.phase === 'uploaded' || file.documents.some(document => document.phase === 'uploaded')) return 'uploaded';
  if (hasError(file) || file.documents.some(hasError)) return 'failed';
  return 'ready';
}

export function ProjectFilesView({
  project, onUpload, onOpenDocument, onStart, onRerun,
  analysisModes, analysisModesLoading, analysisModesError, onRetryAnalysisModes,
  selectedAnalysisMode, onOpenSettings, onRemoveFile,
}: ProjectFilesViewProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>('all');
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const [sort, setSort] = useState('recent');
  const [fileToRemove, setFileToRemove] = useState<ProjectFile | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState('');
  const startLock = useRef(false);
  const removeLock = useRef(false);
  const busy = uploading || starting || removing;
  const selectedModeInfo = analysisModes?.modes.find(mode => mode.id === selectedAnalysisMode);
  const modeReady = !analysisModesLoading && !analysisModesError && selectedModeInfo?.available === true;
  const waiting = project.files.filter(file => fileState(file) === 'uploaded').length;
  const pending = project.files.filter(file => fileState(file) === 'processing').length;
  const hasFiles = project.files.length > 0;
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const filtered = project.files.filter(file => {
    const searchText = [file.name, ...file.documents.flatMap(document => [document.name, document.relativePath ?? ''])]
      .join(' ').toLocaleLowerCase('ru');
    return (statusFilter === 'all' || fileState(file) === statusFilter) && searchText.includes(normalizedQuery);
  }).sort((left, right) => sort === 'name'
    ? left.name.localeCompare(right.name, 'ru', { numeric: true })
    : sort === 'oldest' ? left.addedAt - right.addedAt : right.addedAt - left.addedAt);
  const filters: { value: FileStatusFilter; label: string; count: number }[] = [
    { value: 'all', label: 'Все', count: project.files.length },
    { value: 'uploaded', label: 'Ожидают запуска', count: waiting },
    { value: 'processing', label: 'В обработке', count: pending },
    { value: 'ready', label: 'Готово', count: project.files.filter(file => fileState(file) === 'ready').length },
    { value: 'failed', label: 'С ошибками', count: project.files.filter(file => fileState(file) === 'failed').length },
  ];

  async function runAnalysis() {
    const action = waiting > 0 ? onStart : onRerun;
    if (!action || startLock.current || removeLock.current || fileToRemove || uploading || (waiting === 0 && pending > 0) || !modeReady || !selectedAnalysisMode) return;
    startLock.current = true;
    setStarting(true);
    setStartError('');
    try {
      await action(selectedAnalysisMode);
    } catch (cause) {
      setStartError(cause instanceof Error ? cause.message : 'Не удалось запустить анализ. Попробуйте ещё раз.');
    } finally {
      startLock.current = false;
      setStarting(false);
    }
  }

  function closeRemoveDialog() {
    if (!removeLock.current) { setFileToRemove(null); setRemoveError(''); }
  }

  async function removeFile(event: React.FormEvent) {
    event.preventDefault();
    if (!fileToRemove || removeLock.current || startLock.current || uploading) return;
    removeLock.current = true;
    setRemoving(true);
    setRemoveError('');
    try {
      await onRemoveFile(fileToRemove);
      if (project.files.length === 1) { setQuery(''); setStatusFilter('all'); }
      setFileToRemove(null);
    } catch (cause) {
      setRemoveError(errorMessage(cause));
    } finally {
      removeLock.current = false;
      setRemoving(false);
    }
  }

  return (
    <section className={`secondary-view project-files-view${hasFiles ? ' has-files' : ''}`}>
      <div className={`project-upload-section${hasFiles ? ' has-files' : ''}`}>
        {hasFiles && <h2>Документы <span>{project.files.length}</span></h2>}
        <FileDropzone compact={hasFiles} onUpload={onUpload} disabled={starting || removing || !!fileToRemove} onBusyChange={setUploading} />
        {hasFiles && <div className="project-files-heading-actions">
          {pending > 0 && <span className="processing-count" role="status"><LoaderCircle size={15} className="spin" />В обработке: {pending}</span>}
          {(waiting > 0 || (onRerun && project.files.some(file => file.documents.some(document => document.phase === 'ready' || document.phase === 'failed')))) && (
            <button type="button" className={waiting > 0 ? 'primary-button' : 'secondary-button'} disabled={busy || !!fileToRemove || (waiting === 0 && pending > 0) || !modeReady} onClick={() => void runAnalysis()}>
              {starting ? <LoaderCircle size={15} className="spin" /> : waiting > 0 ? <Play size={15} /> : <RotateCw size={14} />}
              {starting ? 'Запускаем анализ…' : waiting > 0 ? 'Начать анализ' : 'Проверить заново'}
            </button>
          )}
        </div>}
      </div>
      {hasFiles && !modeReady && <div className="project-analysis-summary">
        <span role="status">{analysisModesLoading ? 'Загружаем настройки…' : analysisModesError ? 'Не удалось загрузить настройки.' : 'Выбранный режим недоступен. Выберите другой в настройках.'}</span>
        {analysisModesError && <button onClick={onRetryAnalysisModes}>Повторить</button>}
        {!analysisModesLoading && <button onClick={onOpenSettings}>Открыть настройки</button>}
      </div>}
      {startError && <p className="field-error project-action-error" role="alert">{startError}</p>}
      <div className="project-files-toolbar">
          <div className="file-status-filters" role="group" aria-label="Фильтр файлов по статусу">
            {filters.map(filter => (
              <button key={filter.value} type="button" aria-pressed={statusFilter === filter.value} onClick={() => setStatusFilter(filter.value)}>
                {filter.label}<span>{filter.count}</span>
              </button>
            ))}
          </div>
          <div className="project-file-controls">
          <div className="field-search project-search">
            <Search size={17} aria-hidden="true" />
            <input aria-label="Поиск документов в проекте" placeholder="Найти документ" value={query} onChange={event => setQuery(event.target.value)} />
            {query && <button type="button" className="search-clear" aria-label="Очистить поиск документов" onClick={() => setQuery('')}><X size={16} /></button>}
          </div>
          <label className="project-file-sort">
            <ArrowDownWideNarrow size={16} aria-hidden="true" />
            <span className="sr-only">Сортировка документов</span>
            <select value={sort} onChange={event => setSort(event.target.value)}>
              <option value="recent">Сначала новые</option>
              <option value="oldest">Сначала старые</option>
              <option value="name">По названию</option>
            </select>
          </label>
          </div>
        </div>
      {(normalizedQuery || statusFilter !== 'all') && <p className="project-search-result" role="status">Показано загрузок: {filtered.length} из {project.files.length}</p>}
      <div className="project-file-table-scroll">
        <table className="project-file-table" aria-label="Документы проекта">
          <thead><tr><th scope="col">Название</th><th scope="col">Статус</th><th scope="col">Размер</th><th scope="col">Дата добавления</th><th scope="col"><span className="sr-only">Действия</span></th></tr></thead>
          <tbody>
          {filtered.map(file => {
            const isArchive = file.type === 'zip';
            const Icon = isArchive ? Archive : FileText;
            const singleDocument = !isArchive && file.documents.length === 1 ? file.documents[0] : null;
            const processingState = singleDocument ?? file;
            const canOpen = singleDocument?.phase === 'ready' && singleDocument.hasPreview;
            const canRemove = file.phase === 'uploaded' && file.documents.every(document => document.phase === 'uploaded' || document.phase === 'unsupported');
            return (
              <Fragment key={file.id}>
                <tr className="project-file-table-row">
                  <td><div className="project-file-title-cell">
                  <span className={`file-type-icon ${file.type}`}><Icon size={24} /><small>{file.type.toUpperCase()}</small></span>
                  <div className="project-file-name">
                    <h3>{canOpen ? <button type="button" onClick={() => onOpenDocument(singleDocument)}>{file.name}</button> : file.name}</h3>
                    <p>{isArchive ? `Документов в архиве: ${file.documents.length}` : 'Проверка и обработка документа'}</p>
                    {file.errorMessage && <p className="processing-error-text">{file.errorMessage}</p>}
                    {singleDocument?.errorMessage && singleDocument.errorMessage !== file.errorMessage && <p className="processing-error-text">{singleDocument.errorMessage}</p>}
                    {(singleDocument?.errorMessage || file.errorMessage) && file.rulesChecked > 0 && <p>Предыдущие результаты проверки сохранены.</p>}
                  </div>
                  </div></td>
                  <td className="file-processing">
                    <ProcessingStatus item={processingState} name={file.name} />
                    {processingState.phase === 'ready' && <small>{file.rulesChecked > 0 ? `Проверено правил: ${file.rulesChecked} · Замечаний: ${riskCount(file.counts)}` : 'Нет результатов проверки правил'}</small>}
                    {singleDocument?.phase === 'ready' && !singleDocument.hasPreview && <small>Предпросмотр документа недоступен</small>}
                  </td>
                  <td className="project-file-size">{formatFileSize(file.size)}</td>
                  <td className="project-file-date"><time dateTime={new Date(file.addedAt).toISOString()}>{formatProjectDate(file.addedAt)}</time></td>
                  <td className="project-file-actions">
                  {canOpen && (
                    <button className="secondary-button file-open-button" onClick={() => onOpenDocument(singleDocument)} aria-label={`Открыть документ «${singleDocument.name}»`}>
                      Открыть <ArrowUpRight size={15} />
                    </button>
                  )}
                  {canRemove && <button type="button" className="project-file-remove-button" disabled={busy}
                    title="Удалить файл до начала анализа" aria-label={`Удалить файл «${file.name}»`}
                    onClick={() => { if (!startLock.current && !removeLock.current && !uploading) { setRemoveError(''); setFileToRemove(file); } }}>
                    <Trash2 size={16} />
                  </button>}
                  </td>
                </tr>
                {(isArchive || file.documents.length > 1) && file.documents.length > 0 && (
                  <tr className="project-archive-row"><td colSpan={5}>
                  <div className="project-document-children" aria-label={`Документы загрузки «${file.name}»`}>
                    {file.documents.map(document => (
                      <article className="project-child-document" key={document.id}>
                        <span className="child-document-icon"><FileText size={17} /></span>
                        <div className="project-child-name">
                          <h4>{document.name}</h4>
                          {document.relativePath && document.relativePath !== document.name && <p>{document.relativePath}</p>}
                          <p>{document.type?.toUpperCase() ?? 'Файл'}{document.size !== null ? ` · ${formatFileSize(document.size)}` : ''}{document.totalPages > 0 ? ` · Страниц: ${document.totalPages}` : ''}</p>
                          {document.errorMessage && <p className="processing-error-text">{document.errorMessage}</p>}
                          {document.errorMessage && document.rulesChecked > 0 && <p>Предыдущие результаты проверки сохранены.</p>}
                        </div>
                        <div className="file-processing">
                          <ProcessingStatus item={document} name={document.name} />
                          {document.phase === 'ready' && <small>{document.rulesChecked > 0 ? `Проверено правил: ${document.rulesChecked} · Замечаний: ${riskCount(document.counts)}` : 'Нет результатов проверки правил'}</small>}
                          {document.phase === 'ready' && !document.hasPreview && <small>Предпросмотр недоступен</small>}
                        </div>
                        {document.phase === 'ready' && document.hasPreview && (
                          <button className="secondary-button file-open-button" onClick={() => onOpenDocument(document)} aria-label={`Открыть документ «${document.name}»`}>
                            Открыть <ArrowUpRight size={15} />
                          </button>
                        )}
                      </article>
                    ))}
                  </div>
                  </td></tr>
                )}
                {file.phase === 'ready' && file.documents.length === 0 && <tr><td colSpan={5}><p className="project-no-documents">Для этой загрузки сервер не вернул документов.</p></td></tr>}
              </Fragment>
            );
          })}
          {filtered.length === 0 && <tr><td colSpan={5}><div className="project-files-empty">
          <h3>{project.files.length ? 'Подходящих документов нет' : 'Здесь будут документы проекта'}</h3>
          <p>{project.files.length ? 'Измените поисковый запрос или выберите другой статус.' : 'Добавьте первый файл с помощью кнопки или перетащите его в область выше.'}</p>
          {project.files.length > 0 && <button className="secondary-button" onClick={() => { setQuery(''); setStatusFilter('all'); }}>Сбросить фильтры</button>}
        </div></td></tr>}
          </tbody>
        </table>
      </div>
      {fileToRemove && <Modal title="Удалить файл?" closeDisabled={removing} onClose={closeRemoveDialog}>
        <form onSubmit={event => void removeFile(event)} aria-busy={removing}>
          <div className="project-delete-warning">
            <p>Файл «{fileToRemove.name}» будет удалён из проекта.</p>
            {fileToRemove.type === 'zip' && <p>Все документы из этого ZIP-архива тоже будут удалены.</p>}
          </div>
          {removeError && <p className="field-error" role="alert">{removeError}</p>}
          <div className="modal-actions">
            <button type="button" className="secondary-button" disabled={removing} onClick={closeRemoveDialog}>Отмена</button>
            <button className="primary-button project-delete-confirm" disabled={removing}>
              {removing && <LoaderCircle size={15} className="spin" />}{removing ? 'Удаляем…' : 'Удалить файл'}
            </button>
          </div>
        </form>
      </Modal>}
    </section>
  );
}

function ProcessingStatus({ item, name }: { item: ProcessingState; name: string }) {
  const progress = Math.min(100, Math.max(0, item.progress));
  return (
    <>
      <span className={`file-status ${item.phase}`} role="status">
        {item.phase === 'uploaded' || item.phase === 'queued' ? <Clock3 size={15} />
          : item.phase === 'processing' ? <LoaderCircle size={15} className="spin" />
            : hasError(item) ? <AlertCircle size={15} /> : <Check size={15} />}
        <span>{item.label}</span>
      </span>
      {isPending(item) && (
        <div className="upload-progress-line">
          <div className="upload-progress" role="progressbar" aria-label={`Обработка файла ${name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <small aria-hidden="true">{progress}%</small>
        </div>
      )}
    </>
  );
}

interface FileDropzoneProps {
  compact: boolean;
  onUpload: ProjectFilesViewProps['onUpload'];
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
}

function FileDropzone({ compact, onUpload, disabled, onBusyChange }: FileDropzoneProps) {
  const input = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const uploadLock = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const blocked = disabled || uploading;

  async function accept(files: File[]) {
    if (!files.length || disabled || uploadLock.current) return;
    uploadLock.current = true;
    setUploading(true);
    onBusyChange(true);
    setErrors([]);
    try {
      setErrors(await onUpload(files));
    } catch (cause) {
      setErrors([cause instanceof Error ? cause.message : 'Не удалось загрузить файлы. Попробуйте ещё раз.']);
    } finally {
      uploadLock.current = false;
      setUploading(false);
      onBusyChange(false);
    }
  }

  return (
    <>
      <div
        className={`${compact ? 'file-upload-compact' : 'file-dropzone'} ${dragging && !blocked ? 'is-dragging' : ''} ${blocked ? 'is-uploading' : ''}`}
        aria-busy={uploading}
        onDragEnter={event => { event.preventDefault(); if (blocked) return; dragDepth.current++; setDragging(true); }}
        onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = blocked ? 'none' : 'copy'; }}
        onDragLeave={event => { event.preventDefault(); dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false); }}
        onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); void accept(Array.from(event.dataTransfer.files)); }}
      >
        {!compact && <><span className="upload-icon">{uploading ? <LoaderCircle size={36} className="spin" /> : <UploadCloud size={36} strokeWidth={1.5} />}</span>
        <div className="dropzone-copy">
          <h2>{uploading ? 'Загружаем файлы на сервер…' : dragging && !blocked ? 'Отпустите файлы для загрузки' : 'Загрузите документы'}</h2>
          <p>{uploading ? 'Сохраняем файлы. Анализ можно будет запустить кнопкой «Начать анализ».' : 'Перетащите файлы сюда или выберите на устройстве.'}</p>
          <small id="file-upload-help">DOCX, PDF, ZIP · до {formatFileSize(MAX_FILE_BYTES)} на файл</small>
        </div></>}
        <input
          ref={input} type="file" hidden multiple disabled={blocked} accept={UPLOAD_ACCEPT} aria-label="Выберите документы"
          onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ''; void accept(files); }}
        />
        <button type="button" className={compact ? 'secondary-button' : 'primary-button'} disabled={blocked} aria-describedby={compact ? undefined : 'file-upload-help'} onClick={() => input.current?.click()}>
          {uploading ? <LoaderCircle size={17} className="spin" /> : <UploadCloud size={17} />}{uploading ? 'Загрузка…' : compact ? 'Добавить документы' : 'Выбрать файлы'}
        </button>
      </div>
      {errors.length > 0 && (
        <div className="upload-errors" role="alert">
          <strong>Не удалось добавить файлы:</strong>
          <ul>{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>
        </div>
      )}
    </>
  );
}
