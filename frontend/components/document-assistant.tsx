'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, ChevronDown, ChevronUp, Download, FileText, LoaderCircle, MessageSquare, Sparkles, X } from 'lucide-react';
import { api, errorMessage } from '@/lib/api';
import type { ChatHistory, ChatMessage, ChatMode, ChatSource, Finding } from '@/lib/types';
import './document-assistant.css';

export function DocumentAssistant({ documentId, finding, focusKey, onClearFinding, onSource }: {
  documentId: string;
  finding: Finding | null;
  focusKey: number;
  onClearFinding: () => void;
  onSource: (source: ChatSource) => void;
}) {
  const [history, setHistory] = useState<ChatHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<ChatMode>('question');
  const [expanded, setExpanded] = useState(false);
  const [sending, setSending] = useState(false);
  const [pendingText, setPendingText] = useState('');
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const sendRef = useRef<AbortController | null>(null);
  const downloadRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoadError('');
    api.getDocumentChat(documentId, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setHistory(value);
    }).catch(reason => {
      if (!controller.signal.aborted) setLoadError(errorMessage(reason));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [documentId, revision]);
  useEffect(() => () => { sendRef.current?.abort(); downloadRef.current?.abort(); }, []);
  useEffect(() => {
    if (focusKey) { setExpanded(true); setMode('question'); inputRef.current?.focus(); }
  }, [focusKey]);
  useEffect(() => {
    const log = logRef.current;
    if (log && expanded) log.scrollTop = log.scrollHeight;
  }, [history?.messages.length, pendingText, expanded]);

  const disabled = loading || Boolean(loadError) || !history?.available || sending;
  async function send(question = text, nextMode = mode, wholeDocument = false) {
    const trimmed = question.trim();
    if (disabled || sendRef.current || !trimmed || trimmed.length > 4000) return;
    const controller = new AbortController();
    sendRef.current = controller;
    if (wholeDocument) onClearFinding();
    setSending(true); setExpanded(true); setError(''); setPendingText(trimmed); setText(trimmed); setMode(nextMode);
    try {
      const messages = await api.sendDocumentMessage(documentId, trimmed, {
        signal: controller.signal, findingId: wholeDocument ? undefined : finding?.id, mode: nextMode,
      });
      if (controller.signal.aborted) return;
      setHistory(previous => previous && { ...previous, messages: [...previous.messages, ...messages].slice(-80) });
      setText('');
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason));
    } finally {
      if (!controller.signal.aborted) { setSending(false); setPendingText(''); sendRef.current = null; inputRef.current?.focus(); }
    }
  }
  async function download(message: ChatMessage) {
    if (downloadRef.current) return;
    const controller = new AbortController();
    downloadRef.current = controller; setDownloading(message.id); setError('');
    try { await api.downloadChatDraft(documentId, message.id, { signal: controller.signal }); }
    catch (reason) { if (!controller.signal.aborted) setError(errorMessage(reason)); }
    finally { if (!controller.signal.aborted) { setDownloading(null); downloadRef.current = null; } }
  }

  return <section className="document-assistant" aria-label="ИИ-помощник по документу">
    <div className="assistant-heading">
      <span><Sparkles size={15} /><strong>ИИ-помощник</strong><small>По документу и результатам анализа</small></span>
      <button type="button" aria-expanded={expanded} aria-controls="document-chat-log" onClick={() => setExpanded(!expanded)}>
        {expanded ? 'Свернуть' : history?.messages.length ? `Диалог · ${history.messages.length}` : 'Открыть чат'}{expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
      </button>
    </div>
    <div id="document-chat-log" hidden={!expanded} ref={logRef} className="assistant-log" role="log" aria-label="Диалог по документу" aria-live="polite" aria-relevant="additions text">
      {!history?.messages.length && !pendingText && <p className="assistant-welcome">Спросите о рисках, уточните замечание или подготовьте итоговый документ.</p>}
      {history?.messages.map(message => <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
        <strong>{message.role === 'user' ? 'Вы' : 'ИИ-помощник'}</strong>
        <p>{message.content}</p>
        {message.sources.length > 0 && <div className="assistant-sources" aria-label="Источники ответа">{message.sources.map(source => <button key={source.id} type="button" disabled={!source.findingId && !source.page} onClick={() => { onSource(source); setExpanded(false); }} title={source.quote || source.label}>
          <FileText size={13} />{source.findingId ? source.label : `Стр. ${source.page}`}
        </button>)}</div>}
        {message.draftContent && <div className="assistant-draft">
          <details><summary><FileText size={16} />{message.draftTitle || 'Черновик документа'}</summary><div>{message.draftContent}</div></details>
          <button type="button" onClick={() => void download(message)} disabled={downloading !== null}>
            {downloading === message.id ? <LoaderCircle className="spin" size={14} /> : <Download size={14} />}Скачать Word
          </button>
        </div>}
      </article>)}
      {pendingText && <article className="assistant-message assistant-message-user"><strong>Вы</strong><p>{pendingText}</p></article>}
      {sending && <div className="assistant-pending" role="status"><LoaderCircle className="spin" size={15} />Изучаю документ и готовлю ответ…</div>}
    </div>
    {finding && <div className="assistant-finding"><MessageSquare size={14} /><span>Вопрос по замечанию {finding.number ? `№ ${finding.number}: ` : ''}<strong>{finding.title}</strong></span><button type="button" disabled={sending} onClick={onClearFinding} aria-label="Задать вопрос по всему документу"><X size={14} /></button></div>}
    {loadError && <div className="assistant-error" role="alert">{loadError}<button type="button" onClick={() => setRevision(value => value + 1)}>Повторить загрузку чата</button></div>}
    {!loading && !loadError && history && !history.available && <p className="assistant-unavailable" role="status">{history.unavailableReason || 'ИИ-помощник временно недоступен.'}</p>}
    {error && <div className="assistant-error" role="alert">{error}</div>}
    <form className="assistant-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <FileText className="assistant-document-icon" size={21} />
      <textarea ref={inputRef} aria-label={finding ? 'Вопрос по замечанию' : 'Вопрос по документу'} placeholder={finding ? 'Что уточнить по этому замечанию?' : 'Что вы хотите узнать о документе?'} value={text} disabled={disabled} maxLength={4000} rows={2} onChange={event => setText(event.target.value)} onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
      }} />
      <div className="assistant-send-controls">
        <select aria-label="Режим помощника" value={mode} disabled={disabled} onChange={event => setMode(event.target.value as ChatMode)}>
          <option value="question">Вопрос</option><option value="report">Итоговый отчёт</option><option value="protocol">Протокол разногласий</option>
        </select>
        <button type="submit" className="assistant-send" aria-label="Отправить вопрос" disabled={disabled || !text.trim()}>{sending || loading ? <LoaderCircle size={18} className="spin" /> : <ArrowUp size={19} />}</button>
      </div>
    </form>
    <div className="assistant-suggestions">
      <button type="button" disabled={disabled} onClick={() => void send('Составь краткую сводку основных рисков и укажи, что проверить в первую очередь.', 'question', true)}><Sparkles size={14} />Сводка по рискам</button>
      <button type="button" disabled={disabled} onClick={() => void send('Подготовь итоговый отчёт по текущим результатам анализа с обоснованиями и рекомендациями.', 'report', true)}><FileText size={14} />Подготовить отчёт</button>
      <button type="button" disabled={disabled} onClick={() => void send('Подготовь протокол разногласий по выявленным рискам с предложениями редакций спорных пунктов.', 'protocol', true)}><MessageSquare size={14} />Протокол разногласий</button>
      <small>{text.length > 3500 ? `${text.length}/4000` : 'Enter — отправить · Shift+Enter — новая строка'}</small>
    </div>
  </section>;
}
