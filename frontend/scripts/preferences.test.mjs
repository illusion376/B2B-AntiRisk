import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { defaultPreferences, normalizePreferences, parsePreferences, matchesSeverity } = await loadLib('workspace-preferences');
const { analysisSnapshot, analysisEvents } = await loadLib('analysis-notifications');

test('defaults show every supported level and corrupt storage cannot hide all results', () => {
  assert.deepEqual(defaultPreferences().defaultSeverities, ['critical', 'warning', 'low', 'ok']);
  assert.equal(defaultPreferences().sensitivity, 'balanced');
  for (const raw of [null, '{broken', 'null', '[]', '{"defaultSeverities":[]}', '{"defaultSeverities":["unknown"]}']) {
    assert.deepEqual(parsePreferences(raw).defaultSeverities, defaultPreferences().defaultSeverities);
  }
});

test('saved preferences preserve false flags, deduplicate levels and reject unknown values', () => {
  const value = normalizePreferences({ defaultSeverities: ['warning', 'critical', 'critical', 'oops'], sensitivity: 'sensitive',
    notifications: { completed: false, error: true, critical: false, desktop: false } });
  assert.deepEqual(parsePreferences(JSON.stringify(value)), value);
  assert.deepEqual(value.defaultSeverities, ['critical', 'warning']);
  assert.equal(value.notifications.completed, false);
  assert.equal(normalizePreferences({ sensitivity: 'typo', notifications: { error: 'false' } }).sensitivity, 'balanced');
  assert.equal(normalizePreferences({ notifications: { error: 'false' } }).notifications.error, true);
});

test('default display filter hides unchecked levels while explicit all and single-level filters still work', () => {
  assert.ok(matchesSeverity('critical', 'default', ['critical', 'warning']));
  assert.ok(!matchesSeverity('low', 'default', ['critical', 'warning']));
  assert.ok(matchesSeverity('low', 'all', ['critical']));
  assert.ok(matchesSeverity('ok', 'ok', ['critical']));
  assert.ok(!matchesSeverity('critical', 'ok', ['critical']));
});

const project = (phase, critical = 0, error = null) => [{ id: 'p', title: 'Закупка', files: [{
  id: 'f', name: 'Договор.pdf', phase, errorMessage: error, counts: { critical },
  documents: [{ id: 'd', name: 'Договор.pdf', phase, errorMessage: error, counts: { critical } }],
}] }];

test('completion and critical events follow a finished run and never repeat on unchanged polls or initial results', () => {
  const waiting = analysisSnapshot(project('uploaded'));
  const done = analysisSnapshot(project('ready', 2));
  const events = analysisEvents(waiting, done, 123);
  assert.deepEqual(events.map(event => event.kind), ['completed', 'critical']);
  assert.equal(events[1].documentId, 'd');
  assert.equal(events[1].projectId, 'p');
  assert.deepEqual(analysisEvents(done, done), []);
  assert.deepEqual(analysisEvents(new Map(), done), []);
  assert.deepEqual(analysisEvents(done, new Map()), []);
});

test('queue failures, failed documents inside ZIP and failed reruns produce an error instead of successful completion', () => {
  const before = analysisSnapshot(project('processing'));
  for (const phase of ['ready', 'failed']) {
    const after = analysisSnapshot(project(phase, 0, 'Ошибка обработки'));
    assert.deepEqual(analysisEvents(before, after).map(event => event.kind), ['error']);
    assert.deepEqual(analysisEvents(after, after), []);
  }
  const zip = project('ready');
  zip[0].files[0].documents[0].phase = 'failed';
  assert.deepEqual(analysisEvents(before, analysisSnapshot(zip)).map(event => event.kind), ['error']);
  assert.deepEqual(analysisEvents(analysisSnapshot(project('uploaded')), analysisSnapshot(project('failed'))).map(event => event.kind), ['error']);
  assert.deepEqual(analysisEvents(before, analysisSnapshot(project('ready', 2, 'Часть правил не проверена'))).map(event => event.kind), ['error', 'critical']);
});

test('a repeated run can report critical findings again, independently of the display preference', () => {
  const prefs = normalizePreferences({ defaultSeverities: ['ok'] });
  assert.ok(!matchesSeverity('critical', 'default', prefs.defaultSeverities));
  const events = analysisEvents(analysisSnapshot(project('processing', 2)), analysisSnapshot(project('ready', 2)));
  assert.ok(events.some(event => event.kind === 'critical'));
});
