import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { DEFAULT_ROUTE, formatRoute, normalizeRoute, parseRoute } = await loadLib('routes');
const PAGES = 54;

test('пустой и неизвестный адрес ведут к списку проектов', () => {
  for (const hash of ['', '#', '#/', '#/unknown', '#/projects', '#/projects/a/b/c']) {
    assert.equal(parseRoute(hash, PAGES).view, 'documents', hash);
  }
});

test('документ: проект, страница и замечание восстанавливаются из адреса', () => {
  assert.deepEqual(parseRoute('#/projects/contract-project/document?page=24&finding=2', PAGES), {
    view: 'document', projectId: 'contract-project', page: 24, findingId: 2,
  });
});

test('страница ограничивается документом, мусорные параметры отбрасываются', () => {
  assert.equal(parseRoute('#/projects/p/document?page=999', PAGES).page, PAGES);
  assert.equal(parseRoute('#/projects/p/document?page=0', PAGES).page, DEFAULT_ROUTE.page);
  assert.equal(parseRoute('#/projects/p/document?page=abc', PAGES).page, DEFAULT_ROUTE.page);
  assert.equal(parseRoute('#/projects/p/document?page=2&finding=-3', PAGES).findingId, null);
  assert.equal(normalizeRoute({ ...DEFAULT_ROUTE, page: Number.NaN }, PAGES).page, DEFAULT_ROUTE.page);
});

test('id проекта с кириллицей и пробелами переживает форматирование и разбор', () => {
  const route = { view: 'document', projectId: 'проект 1/2', page: 3, findingId: null };
  const hash = formatRoute(route);
  assert.ok(!hash.includes(' '));
  assert.deepEqual(parseRoute(hash, PAGES), route);
});

test('битая кодировка id проекта не ломает приложение', () => {
  assert.equal(parseRoute('#/projects/%E0%A4%A/document?page=2', PAGES).view, 'documents');
});

test('правила и история сохраняют открытый проект и страницу', () => {
  const previous = { view: 'document', projectId: 'p1', page: 12, findingId: 4 };
  assert.deepEqual(parseRoute('#/rules', PAGES, previous), { ...previous, view: 'rules' });
  assert.equal(formatRoute({ ...previous, view: 'history' }), '#/history');
});

test('format -> parse возвращает тот же маршрут для всех разделов', () => {
  for (const view of ['documents', 'project', 'document', 'rules', 'history']) {
    const route = { view, projectId: 'contract-project', page: 18, findingId: 1 };
    assert.equal(parseRoute(formatRoute(route), PAGES, route).view, view);
  }
});
