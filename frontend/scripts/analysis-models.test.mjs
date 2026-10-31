import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { api, mapAnalysisModels } = await loadLib('api');
const { filterAnalysisModels, savedAnalysisModel } = await loadLib('analysis-models');
const dto = {
  default_model: 'openai/gpt-4.1-mini', source: 'provider', models: [
    { id: 'openai/gpt-4.1-mini', label: 'GPT-4.1 mini', provider: 'OpenAI', provider_id: 'openai', description: 'Проверка', available: true, recommended: true },
    { id: 'anthropic/claude-sonnet-4-5', label: 'Claude Sonnet 4.5', provider: 'Anthropic', provider_id: 'anthropic', description: 'Проверка', available: true, recommended: false },
    { id: 'deepseek/deepseek-v4-flash', label: 'DeepSeek V4 Flash', provider: 'DeepSeek', provider_id: 'deepseek', description: 'Проверка', available: false, recommended: false },
  ],
};
const response = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });

test('catalogue preserves provider IDs, the configured default and unavailable choices', async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/analysis-models');
    assert.equal(options.signal, controller.signal);
    return response(dto);
  });
  const result = await api.getAnalysisModels({ signal: controller.signal });
  assert.equal(result.defaultModel, 'openai/gpt-4.1-mini');
  assert.equal(result.models[1].providerId, 'anthropic');
  assert.equal(result.models[2].available, false);
  assert.equal(result.source, 'provider');
  assert.throws(() => mapAnalysisModels({ ...dto, models: [dto.models[0], dto.models[0]] }));
  assert.throws(() => mapAnalysisModels({ ...dto, models: [{ ...dto.models[0], available: 'yes' }] }));
  assert.throws(() => mapAnalysisModels({ ...dto, source: 'unknown' }));
});

test('model search combines provider filters, names, API identifiers and multiple words', () => {
  const { models } = mapAnalysisModels(dto);
  assert.deepEqual(filterAnalysisModels(models, '  gPt MINI  ', 'all').map(model => model.id), ['openai/gpt-4.1-mini']);
  assert.deepEqual(filterAnalysisModels(models, 'deepseek-v4-flash', 'deepseek').map(model => model.id), ['deepseek/deepseek-v4-flash']);
  assert.equal(filterAnalysisModels(models, 'GPT', 'anthropic').length, 0);
  assert.equal(filterAnalysisModels(models, 'missing', 'all').length, 0);
  assert.equal(filterAnalysisModels(models, '', 'all').length, 3);
});

test('saved model identifiers survive reloads while malformed storage values do not', () => {
  assert.equal(savedAnalysisModel('qwen/qwen-plus'), 'qwen/qwen-plus');
  assert.equal(savedAnalysisModel('old/model-no-longer-available'), 'old/model-no-longer-available');
  for (const value of [null, '', '  ', '../model', 'https://bad host/model', 'model\nname', 'a'.repeat(201)]) {
    assert.equal(savedAnalysisModel(value), null);
  }
});

test('every launch sends the selected model and keyword mode omits it', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });

    return response({ documents: 1 });
  });
  await api.startProjectAnalysis('project', { analysisMode: 'llm', llmModel: 'anthropic/claude-sonnet-4-5' });
  await api.rerunProject('project', { analysisMode: 'llm', llmModel: 'deepseek/deepseek-v4-flash', ruleIds: ['rule'] });
  await assert.rejects(api.reanalyzeDocument('doc', { analysisMode: 'llm', llmModel: 'openai/gpt-4.1-mini' }));
  await api.startProjectAnalysis('project', { analysisMode: 'keyword', llmModel: 'anthropic/claude-sonnet-4-5' });
  assert.deepEqual(calls, [
    { url: '/api/projects/project/start', body: { analysis_mode: 'llm', llm_model: 'anthropic/claude-sonnet-4-5' } },
    { url: '/api/projects/project/rerun', body: { rule_ids: ['rule'], analysis_mode: 'llm', llm_model: 'deepseek/deepseek-v4-flash' } },
    { url: '/api/documents/doc/reanalyze', body: { analysis_mode: 'llm', llm_model: 'openai/gpt-4.1-mini' } },
    { url: '/api/projects/project/start', body: { analysis_mode: 'keyword' } },
  ]);
});

test('a rejected model stays an error and cannot retry with a different paid model', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    calls++;
    return new Response(JSON.stringify({ detail: { code: 'analysis_model_unavailable', message: 'Выберите другую модель.' } }), { status: 422 });
  });
  await assert.rejects(api.startProjectAnalysis('project', { analysisMode: 'llm', llmModel: 'removed/model' }), error => {
    assert.equal(error.status, 422);
    assert.equal(error.message, 'Выберите другую модель.');
    return true;
  });
  assert.equal(calls, 1);
});
