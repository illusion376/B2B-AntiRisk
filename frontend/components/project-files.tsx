'use client';

import { useRef, useState } from 'react';
import { AlertCircle, Archive, ArrowUpRight, Check, Clock3, FileText, FolderOpen, Info, LoaderCircle, RotateCw, Search, UploadCloud, X } from 'lucide-react';
import type { DocumentInfo, ProcessingState, Project, ProjectFile, SeverityCounts } from '@/lib/types';
import { ARCHIVE_FILE_TYPES, formatFileSize, formatProjectDate, MAX_FILE_BYTES, UPLOAD_ACCEPT } from '@/lib/projects';
import './project-enhancements.css';

interface ProjectFilesViewProps {
  project: Project;
  onUpload: (files: File[]) => Promise<string[]>;
  onOpenDocument: (document: DocumentInfo) => void;
  onRerun?: () => Promise<void>;
}

type FileStatusFilter = 'all' | 'processing' | 'ready' | 'failed';
const isPending = (item: ProcessingState) => item.phase === 'queued' || item.phase === 'processing';
const hasError = (item: ProcessingState) => item.phase === 'failed' || item.phase === 'unsupported';
const riskCount = (counts: SeverityCounts) => counts.critical + counts.warning + counts.low;

function fileState(file: ProjectFile): Exclude<FileStatusFilter, 'all'> {
  if (isPending(file) || file.documents.some(isPending)) return 'processing';
  if (hasError(file) || file.documents.some(hasError)) return 'failed';
  return 'ready';
}

export function ProjectFilesView({ project, onUpload, onOpenDocument, onRerun }: ProjectFilesViewProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>('all');
  const [uploading, setUploading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState('');
  const rerunLock = useRef(false);
  const pending = project.files.filter(file => fileState(file) === 'processing').length;
  const documentCount = project.files.reduce((total, file) => total + file.documents.length, 0);
  const normalizedQuery = query.trim().toLocaleLowerCase('ru');
  const filtered = project.files.filter(file => {
    const searchText = [file.name, ...file.documents.flatMap(document => [document.name, document.relativePath ?? ''])]
      .join(' ').toLocaleLowerCase('ru');
    return (statusFilter === 'all' || fileState(file) === statusFilter) && searchText.includes(normalizedQuery);
  });
  const filters: { value: FileStatusFilter; label: string; count: number }[] = [
    { value: 'all', label: 'Все', count: project.files.length },
    { value: 'processing', label: 'В обработке', count: pending },
    { value: 'ready', label: 'Готово', count: project.files.filter(file => fileState(file) === 'ready').length },
    { value: 'failed', label: 'С ошибками', count: project.files.filter(file => fileState(file) === 'failed').length },
  ];

  async function rerunProject() {
    if (!onRerun || rerunLock.current || uploading || pending > 0) return;
    rerunLock.current = true;
    setRerunning(true);
    setRerunError('');
    try {
      await onRerun();
    } catch (cause) {
      setRerunError(cause instanceof Error ? cause.message : 'Не удалось запустить повторную проверку. Попробуйте ещё раз.');
    } finally {
      rerunLock.current = false;
      setRerunning(false);
    }
  }

  return (
    <section className="secondary-view project-files-view">
      <div className="view-title">
        <div>
          <span className="eyebrow">ПРОЕКТ</span>
          <h1>{project.title}</h1>
          <p>{project.description || 'Загрузите документы, чтобы начать работу.'}</p>
        </div>
        <span className="count-chip"><FolderOpen size={17} />Документов: {documentCount}</span>
      </div>
      <FileDropzone onUpload={onUpload} disabled={rerunning} onBusyChange={setUploading} />
      <div className="processing-notice">
        <Info size={17} />
        <p>Документы проверяются на сервере. Архивы ZIP, RAR и 7Z распаковываются, результаты доступны отдельно для каждого документа.</p>
      </div>
      <div className="project-files-heading">
        <h2>Загруженные файлы <span>{project.files.length}</span></h2>
        <div className="project-files-heading-actions">
          {pending > 0 && <span className="processing-count" role="status"><LoaderCircle size={15} className="spin" />В обработке: {pending}</span>}
          {onRerun && project.files.length > 0 && (
            <button type="button" className="secondary-button" disabled={rerunning || uploading || pending > 0} onClick={() => void rerunProject()}>
              <RotateCw size={14} className={rerunning ? 'spin' : ''} />
              {rerunning ? 'Запускаем проверку…' : 'Проверить заново'}
            </button>
          )}
        </div>
      </div>
      {rerunError && <p className="field-error project-action-error" role="alert">{rerunError}</p>}
      {project.files.length > 0 && (
        <div className="project-files-toolbar">
          <div className="file-status-filters" role="group" aria-label="Фильтр файлов по статусу">
            {filters.map(filter => (
              <button key={filter.value} type="button" aria-pressed={statusFilter === filter.value} onClick={() => setStatusFilter(filter.value)}>
                {filter.label}<span>{filter.count}</span>
              </button>
            ))}
          </div>
          <div className="field-search project-search">
            <Search size={17} aria-hidden="true" />
            <input aria-label="Поиск документов в проекте" placeholder="Найти документ" value={query} onChange={event => setQuery(event.target.value)} />
            {query && <button type="button" className="search-clear" aria-label="Очистить поиск документов" onClick={() => setQuery('')}><X size={16} /></button>}
          </div>
        </div>
      )}
      {(normalizedQuery || statusFilter !== 'all') && <p className="project-search-result" role="status">Показано загрузок: {filtered.length} из {project.files.length}</p>}
      {filtered.length > 0 ? (
        <div className="project-file-list">
          {filtered.map(file => {
            const isArchive = ARCHIVE_FILE_TYPES.includes(file.type);
            const Icon = isArchive ? Archive : FileText;
            const singleDocument = !isArchive && file.documents.length === 1 ? file.documents[0] : null;
            const processingState = singleDocument ?? file;
            const canOpen = singleDocument?.phase === 'ready' && singleDocument.hasPreview;
            return (
              <div className="project-upload-group" key={file.id}>
                <article className="project-file-row">
                  <span className={`file-type-icon ${file.type}${isArchive ? ' archive' : ''}`}><Icon size={24} /><small>{file.type.toUpperCase()}</small></span>
                  <div className="project-file-name">
                    <h3>{file.name}</h3>
                    <p>{formatFileSize(file.size)} · {formatProjectDate(file.addedAt)}{isArchive ? ` · Документов: ${file.documents.length}` : ''}</p>
                    {file.errorMessage && <p className="processing-error-text">{file.errorMessage}</p>}
                    {singleDocument?.errorMessage && singleDocument.errorMessage !== file.errorMessage && <p className="processing-error-text">{singleDocument.errorMessage}</p>}
                  </div>
                  <div className="file-processing">
                    <ProcessingStatus item={processingState} name={file.name} />
                    {processingState.phase === 'ready' && <small>{file.rulesChecked > 0 ? `Проверено правил: ${file.rulesChecked} · Замечаний: ${riskCount(file.counts)}` : 'Нет результатов проверки правил'}</small>}
                    {singleDocument?.phase === 'ready' && !singleDocument.hasPreview && <small>Предпросмотр документа недоступен</small>}
                  </div>
                  {canOpen && (
                    <button className="secondary-button file-open-button" onClick={() => onOpenDocument(singleDocument)} aria-label={`Открыть документ «${singleDocument.name}»`}>
                      Открыть <ArrowUpRight size={15} />
                    </button>
                  )}
                </article>
                {(isArchive || file.documents.length > 1) && file.documents.length > 0 && (
                  <div className="project-document-children" aria-label={`Документы загрузки «${file.name}»`}>
                    {file.documents.map(document => (
                      <article className="project-child-document" key={document.id}>
                        <span className="child-document-icon"><FileText size={17} /></span>
                        <div className="project-child-name">
                          <h4>{document.name}</h4>
                          {document.relativePath && document.relativePath !== document.name && <p>{document.relativePath}</p>}
                          <p>{document.type?.toUpperCase() ?? 'Файл'}{document.size !== null ? ` · ${formatFileSize(document.size)}` : ''}{document.totalPages > 0 ? ` · Страниц: ${document.totalPages}` : ''}</p>
                          {document.errorMessage && <p className="processing-error-text">{document.errorMessage}</p>}
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
                )}
                {file.phase === 'ready' && file.documents.length === 0 && <p className="project-no-documents">Для этой загрузки сервер не вернул документов.</p>}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="project-files-empty">
          <FileText size={27} />
          <h3>{project.files.length ? 'Подходящих документов нет' : 'Здесь будут документы проекта'}</h3>
          <p>{project.files.length ? 'Измените поисковый запрос или выберите другой статус.' : 'Добавьте первый файл с помощью кнопки или перетащите его в область выше.'}</p>
          {project.files.length > 0 && <button className="secondary-button" onClick={() => { setQuery(''); setStatusFilter('all'); }}>Сбросить фильтры</button>}
        </div>
      )}
    </section>
  );
}

function ProcessingStatus({ item, name }: { item: ProcessingState; name: string }) {
  const progress = Math.min(100, Math.max(0, item.progress));
  return (
    <>
      <span className={`file-status ${item.phase}`} role="status">
        {item.phase === 'queued' ? <Clock3 size={15} />
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
  onUpload: ProjectFilesViewProps['onUpload'];
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
}

function FileDropzone({ onUpload, disabled, onBusyChange }: FileDropzoneProps) {
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
        className={`file-dropzone ${dragging && !blocked ? 'is-dragging' : ''} ${blocked ? 'is-uploading' : ''}`}
        aria-busy={uploading}
        onDragEnter={event => { event.preventDefault(); if (blocked) return; dragDepth.current++; setDragging(true); }}
        onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = blocked ? 'none' : 'copy'; }}
        onDragLeave={event => { event.preventDefault(); dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false); }}
        onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); void accept(Array.from(event.dataTransfer.files)); }}
      >
        <span className="upload-icon">{uploading ? <LoaderCircle size={30} className="spin" /> : <UploadCloud size={30} strokeWidth={1.5} />}</span>
        <div className="dropzone-copy">
          <h2>{uploading ? 'Загружаем файлы на сервер…' : dragging && !blocked ? 'Отпустите файлы для загрузки' : 'Загрузите документы'}</h2>
          <p>{uploading ? 'После загрузки проверка начнётся автоматически.' : 'Перетащите файлы сюда или выберите на устройстве.'}</p>
          <small id="file-upload-help">PDF, DOCX, DOC, RTF, ODT, TXT, PNG, JPEG, TIFF, BMP, ZIP, RAR, 7Z · до {formatFileSize(MAX_FILE_BYTES)} на файл</small>
        </div>
        <input
          ref={input} type="file" hidden multiple disabled={blocked} accept={UPLOAD_ACCEPT} aria-label="Выберите документы"
          onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ''; void accept(files); }}
        />
        <button type="button" className="primary-button" disabled={blocked} aria-describedby="file-upload-help" onClick={() => input.current?.click()}>
          <UploadCloud size={17} />{uploading ? 'Загрузка…' : 'Выбрать файлы'}
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
