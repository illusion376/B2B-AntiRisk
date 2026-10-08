import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { api, ApiError, mapProject, mapFinding, mapPage, rulePayload } = await loadLib('api');
const { getProcessing, validateUpload, MAX_FILE_BYTES } = await loadLib('projects');
const created = '2026-10-07T06:30:00+00:00';
const counts = { critical: 1, warning: 2, low: 0, ok: 3, unseen: 2 };
const document = {
  id: 'document-uuid', analysis_id: 'analysis-uuid', file_name: 'Договор.docx', relative_path: 'folder/Договор.docx',
  file_type: 'docx', file_size: 500, status: 'OCR', phase: 'processing', label: 'Распознавание текста', progress: 32,
  total_pages: 2, is_scanned: true, ocr_pages: 1, ocr_confidence: 89.5, law_type: '44-FZ',
  risk_score: null, traffic_light: null, counts, rules_checked: 0, error_message: null,
  processing_ms: null, has_preview: true, created_at: created, updated_at: null,
};
const file = {
  id: 'analysis-uuid', name: 'Пакет.zip', type: 'zip', size: 512, added_at: created,
  phase: 'processing', label: 'Обрабатывается', progress: 32, status: 'OCR', error_message: null,
  risk_score: null, traffic_light: null, counts, rules_checked: 0, documents: [document],
};
const project = {
  id: 'project-uuid', title: 'Закупка', description: '', created_at: created, updated_at: created,
  files: [file], processing_count: 1, counts, traffic_light: null,
};
const finding = {
  id: 'finding-uuid', number: null, document_id: document.id, rule_id: 'payment_deadline',
  title: 'Срок оплаты', description: 'Условие не найдено', severity: 'warning', category: 'Оплата',
  clause: '', page: null, quote: '', recommendation: 'Уточните условия.', comment: '', legal_reference: null,
  highlights: [], quote_verified: false, confidence: null, source: 'HEURISTIC', status: 'unseen',
  reviewer_comment: null, reviewed_at: null, created_at: created,
};
const response = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });

test('API project keeps analysis and document identifiers separate and exposes server processing state', () => {
  const mapped = mapProject(project);
  assert.equal(mapped.updatedAt, Date.parse(created));
  assert.equal(mapped.files[0].id, 'analysis-uuid');
  assert.equal(mapped.files[0].documents[0].id, 'document-uuid');
  assert.equal(mapped.files[0].documents[0].analysisId, mapped.files[0].id);
  assert.equal(mapped.files[0].documents[0].relativePath, 'folder/Договор.docx');
  assert.equal(mapped.files[0].documents[0].updatedAt, null);
  assert.deepEqual(getProcessing(mapped.files[0], Date.now() + 24 * 60 * 60 * 1000), {
    phase: 'processing', progress: 32, label: 'Обрабатывается',
  });
});

test('findings preserve UUIDs and absent page/number instead of inventing a text location', () => {
  const mapped = mapFinding(finding);
  assert.equal(mapped.id, 'finding-uuid');
  assert.equal(mapped.ruleId, 'payment_deadline');
  assert.equal(mapped.page, null);
  assert.equal(mapped.number, null);
  assert.equal(mapped.quoteVerified, false);
  assert.equal(mapped.source, 'HEURISTIC');
});

test('one paragraph can carry several findings and preserves the exact text', () => {
  const mapped = mapPage({
    page: 1, total_pages: 2, width: 595, height: 842, is_ocr: false, ocr_confidence: null,
    sections: [{ title: '', paragraphs: [{ clause: '1.1', text: 'Оплата\u00a0в срок', finding_ids: ['risk-a', 'risk-b'] }] }],
  });
  assert.equal(mapped.totalPages, 2);
  assert.deepEqual(mapped.sections[0].paragraphs[0], { clause: '1.1', text: 'Оплата\u00a0в срок', findingIds: ['risk-a', 'risk-b'] });
});

test('multipart upload sends actual file bytes and preserves partial upload failures', async t => {
  const controller = new AbortController();
  const bytes = new File(['contract content'], 'Договор.txt', { type: 'text/plain' });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/projects/project-uuid/files');
    assert.equal(options.method, 'POST');
    assert.equal(options.signal, controller.signal);
    assert.equal(new Headers(options.headers).get('Content-Type'), null, 'browser must generate the multipart boundary');
    assert.ok(options.body instanceof FormData);
    assert.equal(options.body.get('law_type'), 'AUTO');
    assert.equal(await options.body.get('files').text(), 'contract content');
    return response({ files: [file], errors: [{ name: 'broken.pdf', detail: 'Файл повреждён' }] });
  });
  const result = await api.uploadFiles(project.id, [bytes], { signal: controller.signal });
  assert.equal(result.files[0].documents[0].id, document.id);
  assert.deepEqual(result.errors, [{ name: 'broken.pdf', detail: 'Файл повреждён' }]);
});

test('HTTP validation errors expose useful details and a status for the UI', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'title'], msg: 'String should have at least 1 character' }] }), { status: 422 }));
  await assert.rejects(api.createProject({ title: '', description: '' }), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 422);
    assert.match(error.message, /title: String should/);
    return true;
  });
});

test('uploaded files remain waiting and analysis starts through a separate request', async t => {
  const waiting = { ...file, status: 'UPLOADED', phase: 'uploaded', label: 'Ожидает запуска', progress: 0,
    documents: [{ ...document, status: 'UPLOADED', phase: 'uploaded', label: 'Ожидает запуска', progress: 0 }] };
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push(url);
    if (url.endsWith('/files')) return response({ files: [waiting], errors: [] });
    assert.equal(url, '/api/projects/project-uuid/start');
    assert.equal(options.method, 'POST');
    return response({ documents: 1 });
  });
  const upload = await api.uploadFiles(project.id, [new File(['contract'], 'contract.txt')]);
  assert.equal(upload.files[0].phase, 'uploaded');
  assert.equal(upload.files[0].documents[0].phase, 'uploaded');
  assert.deepEqual(calls, ['/api/projects/project-uuid/files']);
  assert.deepEqual(await api.startProjectAnalysis(project.id), { documents: 1 });
});

test('proxy HTML and malformed success responses cannot become successful empty screens', async t => {
  const mock = t.mock.method(globalThis, 'fetch', async () => new Response('<html>upstream secret</html>', { status: 502 }));
  await assert.rejects(api.getProjects(), error => error.status === 502 && !error.message.includes('upstream secret'));
  mock.mock.mockImplementation(async () => new Response('<html>not JSON</html>', { status: 200 }));
  await assert.rejects(api.getProjects(), /некорректный ответ/);
  mock.mock.mockImplementation(async () => response({ incorrect: [] }));
  await assert.rejects(api.getProjects(), /Формат данных/);
});

test('network failures are friendly and cancellation stays cancellation', async t => {
  const mock = t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(api.getUser(), error => error.status === 0 && /связаться с сервером/.test(error.message));
  const aborted = new DOMException('Aborted', 'AbortError');
  mock.mock.mockImplementation(async () => { throw aborted; });
  await assert.rejects(api.getUser(), error => error === aborted);
});

test('partial rule edits omit derived prompt fields so the backend can regenerate them', async t => {
  const payload = JSON.parse(JSON.stringify(rulePayload({ title: 'Новый срок оплаты', enabled: false })));
  assert.deepEqual(payload, { title: 'Новый срок оплаты', enabled: false });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/findings/finding-uuid');
    assert.deepEqual(JSON.parse(options.body), { status: 'accepted', reviewer_comment: 'Проверено' });
    return response({ ...finding, status: 'accepted', reviewer_comment: 'Проверено' });
  });
  assert.equal((await api.updateFinding(finding.id, { status: 'accepted', reviewerComment: 'Проверено' })).reviewerComment, 'Проверено');
});

test('download failures reject before creating a browser download', async t => {
  t.mock.method(globalThis, 'fetch', async (url) => {
    assert.match(url, /mode=annotated&format=pdf/);
    return new Response(JSON.stringify({ detail: 'Проверка ещё не завершена' }), { status: 409 });
  });
  await assert.rejects(api.downloadReport(document.id, { mode: 'annotated', format: 'docx' }), error => error.status === 409 && error.message === 'Проверка ещё не завершена');
});

test('upload validation matches backend formats and the 100 MB default limit', () => {
  assert.equal(validateUpload({ name: 'Документ.docx', size: 100 }, []), null);
  assert.equal(validateUpload({ name: 'scan.tiff', size: MAX_FILE_BYTES }, []), null);
  assert.match(validateUpload({ name: 'a.pdf', size: MAX_FILE_BYTES + 1 }, []), /100 МБ/);
  assert.match(validateUpload({ name: 'scan.webp', size: 100 }, []), /Поддерживаются/);
});
