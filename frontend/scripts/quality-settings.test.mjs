import test from 'node:test';
import assert from 'node:assert/strict';
import { loadLib } from './load-lib.mjs';

const { api, ApiError, mapUser } = await loadLib('api');
const { MAX_PROCESSING_SLA_SECONDS, mapQualitySettings, parseQualitySettings } = await loadLib('quality-settings');

const user = {
  id: 'user-id', email: 'lawyer@example.test', full_name: 'Иван Иванов',
  company_name: 'ООО «Поставщик»', role: 'USER', initials: 'ИИ',
};
const settings = { ocr_min_confidence: 80, processing_sla_seconds: 120 };
const response = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('user settings use server values, including zero confidence and no time limit', () => {
  assert.deepEqual(mapUser({ ...user, quality_settings: settings }).qualitySettings, {
    ocrMinConfidence: 80, processingSlaSeconds: 120,
  });
  assert.deepEqual(mapUser({ ...user, quality_settings: { ocr_min_confidence: 0, processing_sla_seconds: null } }).qualitySettings, {
    ocrMinConfidence: 0, processingSlaSeconds: null,
  });
  assert.deepEqual(mapUser({ ...user, quality_settings: { ocr_min_confidence: 92.75, processing_sla_seconds: 1 } }).qualitySettings, {
    ocrMinConfidence: 92.75, processingSlaSeconds: 1,
  });
});

test('legacy users do not appear to have saved default quality settings', () => {
  assert.equal(mapUser(user).qualitySettings, null);
  assert.equal(mapUser({ ...user, quality_settings: null }).qualitySettings, null);
});

test('malformed server settings are rejected instead of normalized into valid-looking values', () => {
  for (const value of [-1, 100.01, NaN, Infinity, -Infinity, '80', true, null, undefined]) {
    assert.throws(() => mapQualitySettings({ ...settings, ocr_min_confidence: value }), /распознавания/, `confidence=${String(value)}`);
  }
  for (const value of [-1, 0, 1.5, MAX_PROCESSING_SLA_SECONDS + 1, Infinity, '120', true, undefined]) {
    assert.throws(() => mapQualitySettings({ ...settings, processing_sla_seconds: value }), /Нормативное время/, `duration=${String(value)}`);
  }
  assert.throws(() => mapQualitySettings({}), /распознавания/);
});

test('form allows threshold boundaries and decimals and clears an optional time limit', () => {
  assert.deepEqual(parseQualitySettings({ ocrMinConfidence: '0', processingSlaSeconds: '' }), { ocrMinConfidence: 0, processingSlaSeconds: null });
  assert.deepEqual(parseQualitySettings({ ocrMinConfidence: '100', processingSlaSeconds: '1' }), { ocrMinConfidence: 100, processingSlaSeconds: 1 });
  assert.deepEqual(parseQualitySettings({ ocrMinConfidence: ' 85.25 ', processingSlaSeconds: '   ' }), { ocrMinConfidence: 85.25, processingSlaSeconds: null });
  assert.deepEqual(parseQualitySettings({ ocrMinConfidence: '80', processingSlaSeconds: String(MAX_PROCESSING_SLA_SECONDS) }), { ocrMinConfidence: 80, processingSlaSeconds: MAX_PROCESSING_SLA_SECONDS });
});

test('blank threshold is not converted to zero and invalid form values are rejected', () => {
  for (const value of ['', '   ', '-0.1', '100.01', 'Infinity', 'NaN', 'текст']) {
    assert.throws(() => parseQualitySettings({ ocrMinConfidence: value, processingSlaSeconds: '' }), /распознавания/, `confidence=${value}`);
  }
  for (const value of ['0', '-1', '0.5', '1.25', String(MAX_PROCESSING_SLA_SECONDS + 1), 'Infinity', 'NaN', 'текст']) {
    assert.throws(() => parseQualitySettings({ ocrMinConfidence: '80', processingSlaSeconds: value }), /Нормативное время/, `duration=${value}`);
  }
});

test('quality PATCH uses existing user route, sends only settings and preserves the abort signal', async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/users/me');
    assert.equal(options.method, 'PATCH');
    assert.equal(options.signal, controller.signal);
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), { quality_settings: { ocr_min_confidence: 90.5, processing_sla_seconds: 45 } });
    return response({ ...user, quality_settings: { ocr_min_confidence: 90.5, processing_sla_seconds: 45 } });
  });
  const saved = await api.updateQualitySettings({ ocrMinConfidence: 90.5, processingSlaSeconds: 45 }, { signal: controller.signal });
  assert.deepEqual(saved.qualitySettings, { ocrMinConfidence: 90.5, processingSlaSeconds: 45 });
  assert.equal(saved.fullName, user.full_name);
  assert.equal(saved.companyName, user.company_name);
});

test('clearing time limit sends explicit null while keeping a valid zero threshold', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    const payload = JSON.parse(options.body);
    assert.deepEqual(payload, { quality_settings: { ocr_min_confidence: 0, processing_sla_seconds: null } });
    return response({ ...user, ...payload });
  });
  const saved = await api.updateQualitySettings(parseQualitySettings({ ocrMinConfidence: '0', processingSlaSeconds: '' }));
  assert.deepEqual(saved.qualitySettings, { ocrMinConfidence: 0, processingSlaSeconds: null });
});

test('invalid settings are rejected before an API request can overwrite stored values', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw new Error('Unexpected request'); });
  for (const value of [NaN, Infinity, -1, 101, null, true, '80']) {
    await assert.rejects(api.updateQualitySettings({ ocrMinConfidence: value, processingSlaSeconds: 10 }), /распознавания/);
  }
  for (const value of [undefined, 0, 1.1, MAX_PROCESSING_SLA_SECONDS + 1, true, '10']) {
    await assert.rejects(api.updateQualitySettings({ ocrMinConfidence: 80, processingSlaSeconds: value }), /Нормативное время/);
  }
  assert.equal(fetch.mock.callCount(), 0);
});

test('save failure propagates the server error without retries or invented saved values', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: 'Настройки не сохранены' }), { status: 422 }));
  await assert.rejects(api.updateQualitySettings({ ocrMinConfidence: 80, processingSlaSeconds: null }), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 422);
    assert.equal(error.message, 'Настройки не сохранены');
    return true;
  });
  assert.equal(fetch.mock.callCount(), 1);
});

test('an old server may load a profile but cannot falsely confirm saved quality settings', async t => {
  t.mock.method(globalThis, 'fetch', async () => response(user));
  assert.equal((await api.getUser()).qualitySettings, null);
  await assert.rejects(api.updateQualitySettings({ ocrMinConfidence: 80, processingSlaSeconds: null }), error => error instanceof ApiError && /Формат данных/.test(error.message));
});

test('profile PATCH does not send quality settings and retains them from the server response', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), { full_name: 'Анна Иванова', company_name: null });
    return response({ ...user, full_name: 'Анна Иванова', company_name: null, quality_settings: settings });
  });
  const saved = await api.updateUser({ fullName: ' Анна Иванова ', companyName: '' });
  assert.equal(saved.fullName, 'Анна Иванова');
  assert.deepEqual(saved.qualitySettings, { ocrMinConfidence: 80, processingSlaSeconds: 120 });
});
