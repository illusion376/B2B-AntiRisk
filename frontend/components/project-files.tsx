'use client';

import { useRef, useState } from 'react';
import { Archive, ArrowUpRight, Check, Clock3, FileText, FolderOpen, Info, LoaderCircle, UploadCloud } from 'lucide-react';
import type { Project } from '@/lib/types';
import { formatFileSize, formatProjectDate, getProcessing } from '@/lib/projects';
import { useProcessingClock } from './use-processing-clock';

export function ProjectFilesView({project,onUpload,onOpenDemo}: {project:Project;onUpload:(files:File[])=>string[];onOpenDemo:()=>void}) {
  const now = useProcessingClock(project.files);
  const pending = project.files.filter(file=>getProcessing(file,now).phase!=='ready').length;
  return <section className="secondary-view project-files-view">
    <div className="view-title"><div><span className="eyebrow">ПРОЕКТ</span><h1>{project.title}</h1><p>{project.description || 'Загрузите документы, чтобы начать работу.'}</p></div><span className="count-chip"><FolderOpen size={17} />Файлов: {project.files.length}</span></div>
    <FileDropzone onUpload={onUpload} />
    <div className="processing-notice"><Info size={17} /><p>Обработка работает в деморежиме. Файлы не отправляются на сервер; сохраняются только их названия, размеры и статусы. Анализ содержимого и распаковка ZIP пока не выполняются.</p></div>
    <div className="project-files-heading"><h2>Документы проекта <span>{project.files.length}</span></h2>{pending>0 && <span className="processing-count" role="status"><LoaderCircle size={15} className="spin" />В обработке: {pending}</span>}</div>
    {project.files.length ? <div className="project-file-list">{project.files.map(file=>{
      const processing=getProcessing(file,now);
      const Icon=file.type==='zip'?Archive:FileText;
      return <article className="project-file-row" key={file.id}>
        <span className={`file-type-icon ${file.type}`}><Icon size={24} /><small>{file.type.toUpperCase()}</small></span>
        <div className="project-file-name"><h3>{file.name}</h3><p>{file.source==='demo'?'54 страницы · демопример':`${formatFileSize(file.size)} · ${formatProjectDate(file.addedAt)}`}</p></div>
        <div className="file-processing"><span className={`file-status ${processing.phase}`} role="status">{processing.phase==='queued'?<Clock3 size={15}/>:processing.phase==='processing'?<LoaderCircle size={15} className="spin"/>:<Check size={15}/>}<span>{processing.label}</span></span>{processing.phase!=='ready' && <div className="upload-progress-line"><div className="upload-progress" role="progressbar" aria-label={`Демо-обработка файла ${file.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={processing.progress}><i style={{width:`${processing.progress}%`}} /></div><small aria-hidden="true">{processing.progress}%</small></div>}{file.source==='upload' && processing.phase==='ready' && <small>Результаты анализа пока недоступны</small>}</div>
        {file.source==='demo' && <button className="secondary-button file-open-button" onClick={onOpenDemo}>Открыть <ArrowUpRight size={15}/></button>}
      </article>;
    })}</div> : <div className="project-files-empty"><FileText size={27}/><h3>Здесь будут документы проекта</h3><p>Добавьте первый файл с помощью кнопки или перетащите его в область выше.</p></div>}
  </section>;
}

function FileDropzone({onUpload}: {onUpload:(files:File[])=>string[]}) {
  const input=useRef<HTMLInputElement>(null);
  const dragDepth=useRef(0);
  const [dragging,setDragging]=useState(false);
  const [errors,setErrors]=useState<string[]>([]);
  function accept(files:File[]) { if(files.length)setErrors(onUpload(files)); }
  return <><div className={`file-dropzone ${dragging?'is-dragging':''}`} onDragEnter={event=>{event.preventDefault();dragDepth.current++;setDragging(true);}} onDragOver={event=>{event.preventDefault();event.dataTransfer.dropEffect='copy';}} onDragLeave={event=>{event.preventDefault();dragDepth.current=Math.max(0,dragDepth.current-1);if(!dragDepth.current)setDragging(false);}} onDrop={event=>{event.preventDefault();dragDepth.current=0;setDragging(false);accept(Array.from(event.dataTransfer.files));}}>
    <span className="upload-icon"><UploadCloud size={30} strokeWidth={1.5}/></span><div className="dropzone-copy"><h2>{dragging?'Отпустите файлы для загрузки':'Загрузите документы'}</h2><p>Перетащите файлы сюда или выберите на устройстве.</p><small id="file-upload-help">PDF, TXT, ZIP · до 50 МБ на файл · можно выбрать несколько</small></div>
    <input ref={input} type="file" hidden multiple accept=".pdf,.txt,.zip,application/pdf,text/plain,application/zip,application/x-zip-compressed" aria-label="Выберите документы" onChange={event=>{accept(Array.from(event.target.files??[]));event.target.value='';}} />
    <button type="button" className="primary-button" aria-describedby="file-upload-help" onClick={()=>input.current?.click()}><UploadCloud size={17}/>Выбрать файлы</button>
  </div>{errors.length>0 && <div className="upload-errors" role="alert"><strong>Не удалось добавить некоторые файлы:</strong><ul>{errors.map((error,index)=><li key={index}>{error}</li>)}</ul></div>}</>;
}
