import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { api, mapChatMessage } = await loadLib('api');
const message = { id: 'message-1', role: 'assistant', content: 'Обратите внимание на штраф.', finding_id: 'finding-1',
  sources: [{ id: 'finding-1', label: 'Штраф', page: 2, finding_id: 'finding-1', quote: '10 процентов' }],
  draft_title: null, draft_content: null, created_at: '2026-10-15T12:00:00Z' };

test('chat sends only question, mode and selected finding, preserving cancellation', async () => {
  const controller = new AbortController();
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/documents/doc%2F1/chat');
    assert.equal(options.signal, controller.signal);
    assert.deepEqual(JSON.parse(options.body), { message: 'Почему?', mode: 'question', finding_id: 'finding-1' });
    return Response.json({ messages: [message] });
  };
  try {
    const response = await api.sendDocumentMessage('doc/1', ' Почему? ', { findingId: 'finding-1', signal: controller.signal });
    assert.equal(response[0].sources[0].findingId, 'finding-1');
    assert.equal(response[0].sources[0].page, 2);
  } finally { globalThis.fetch = previous; }
});

test('history preserves unavailable provider reason and saved messages', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ available: false, unavailable_reason: 'Нет настройки', messages: [message] });
  try {
    const history = await api.getDocumentChat('doc');
    assert.equal(history.available, false);
    assert.equal(history.unavailableReason, 'Нет настройки');
    assert.equal(history.messages.length, 1);
  } finally { globalThis.fetch = previous; }
});

test('malformed messages and source locations are not accepted', () => {
  assert.throws(() => mapChatMessage({ ...message, role: 'system' }));
  assert.throws(() => mapChatMessage({ ...message, content: ' ' }));
  assert.throws(() => mapChatMessage({ ...message, sources: [{ ...message.sources[0], page: -1 }] }));
  assert.throws(() => mapChatMessage({ ...message, draft_content: {} }));
});

test('provider error stays an error and cannot become an empty successful turn', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: 'Помощник не настроен' }, { status: 503 });
  try { await assert.rejects(api.sendDocumentMessage('doc', 'Вопрос'), /Помощник не настроен/); }
  finally { globalThis.fetch = previous; }
});
