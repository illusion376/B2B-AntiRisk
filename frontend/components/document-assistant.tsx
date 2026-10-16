'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Download, FileText, LoaderCircle, MessageSquare, X } from 'lucide-react';
import { api, errorMessage } from '@/lib/api';
import type { ChatHistory, ChatMessage, ChatSource, Finding } from '@/lib/types';
import './document-assistant.css';

export function DocumentAssistant({ documentId, active, finding, focusKey, onClearFinding, onSource }: {
  documentId: string;
  active: boolean;
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
    if (active && focusKey && !loading) inputRef.current?.focus();
  }, [active, focusKey, loading]);
  useEffect(() => {
    const log = logRef.current;
    if (log && active) log.scrollTop = log.scrollHeight;
  }, [history?.messages.length, pendingText, active]);

  const disabled = loading || Boolean(loadError) || !history?.available || sending;
  async function send() {
    const trimmed = text.trim();
    if (disabled || sendRef.current || !trimmed || trimmed.length > 4000) return;
    const controller = new AbortController();
    sendRef.current = controller;
    setSending(true); setError(''); setPendingText(trimmed); setText(trimmed);
    try {
      const messages = await api.sendDocumentMessage(documentId, trimmed, {
        signal: controller.signal, findingId: finding?.id,
      });
      if (controller.signal.aborted) return;
      setHistory(previous => previous && { ...previous, messages: [...previous.messages, ...messages].slice(-80) });
      setText('');
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason));
    } finally {
      if (!controller.signal.aborted) { setSending(false); setPendingText(''); sendRef.current = null; }
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
    <div id="document-chat-log" ref={logRef} className="assistant-log" role="log" aria-label="Диалог по документу" aria-live="polite" aria-relevant="additions text">
      {!history?.messages.length && !pendingText && <div className="assistant-welcome"><MessageSquare size={24} /><strong>Чем помочь с документом?</strong><p>Задайте вопрос или выберите замечание в результатах проверки.</p></div>}
      {history?.messages.map(message => <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
        <strong>{message.role === 'user' ? 'Вы' : 'ИИ-помощник'}</strong>
        <p>{message.content}</p>
        {message.sources.length > 0 && <div className="assistant-sources" aria-label="Источники ответа">{message.sources.map(source => <button key={source.id} type="button" disabled={!source.findingId && !source.page} onClick={() => onSource(source)} title={source.quote || source.label}>
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
      <textarea ref={inputRef} aria-label={finding ? 'Вопрос по замечанию' : 'Вопрос по документу'} placeholder={finding ? 'Что уточнить по этому замечанию?' : 'Вопрос по документу…'} value={text} disabled={disabled} maxLength={4000} rows={2} onChange={event => setText(event.target.value)} onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
      }} />
      <button type="submit" className="assistant-send" aria-label="Отправить вопрос" disabled={disabled || !text.trim()}>{sending || loading ? <LoaderCircle size={18} className="spin" /> : <ArrowUp size={19} />}</button>
    </form>
  </section>;
}
