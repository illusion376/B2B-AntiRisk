import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const {
  asRuleTestDocument, isRuleTestDocumentProcessing, isRuleTestDocumentReady, mergeRuleTestDocuments,
  projectRuleTestDocuments, RULE_TEST_UPLOAD_ACCEPT, ruleTestDocumentLabel, ruleTestDocumentWarning, validateRuleTestUpload,
} = await loadLib('rule-test-documents');
const { MAX_FILE_BYTES } = await loadLib('projects');

const ready = { id: 'normal', name: 'Договор.pdf', projectTitle: 'Закупка', status: 'COMPLETED', phase: 'ready', progress: 100 };

test('test documents precede normal documents, preserving server order and deduplicating by document id', () => {
  const older = { ...ready, id: 'test-old', isTest: true };
  const newer = { ...ready, id: 'test-new', isTest: true };
  const documents = mergeRuleTestDocuments([newer, older], [ready, { ...older, isTest: false }]);
  assert.deepEqual(documents.map(document => document.id), ['test-new', 'test-old', 'normal']);
  assert.equal(documents[1].isTest, true);
  assert.equal(documents[2], ready);
});

test('the test marker depends on the server project flag and leaves stored names unchanged', () => {
  const document = { ...ready, errorMessage: null };
  const normalProject = { title: 'Тестовые документы', isRuleTest: false, files: [{ documents: [document] }] };
  assert.deepEqual(projectRuleTestDocuments(normalProject), []);
  const testDocuments = projectRuleTestDocuments({ ...normalProject, isRuleTest: true });
  assert.equal(testDocuments[0].isTest, true);
  assert.equal(testDocuments[0].name, 'Договор.pdf');
  assert.equal(testDocuments[0].projectTitle, undefined);
  assert.equal(ruleTestDocumentLabel(testDocuments[0]), '[Тест] Договор.pdf ✓');
  assert.equal(ruleTestDocumentLabel(ready), 'Закупка / Договор.pdf ✓');
});

test('a freshly uploaded document retains its id, progress and preparation failure', () => {
  const source = { ...ready, id: 'uploaded', phase: 'processing', status: 'OCR', progress: 40, errorMessage: null };
  const mapped = asRuleTestDocument(source);
  assert.equal(mapped.id, source.id);
  assert.equal(mapped.progress, 40);
  assert.equal(isRuleTestDocumentProcessing(mapped), true);
  assert.equal(isRuleTestDocumentReady(mapped), false);
  assert.equal(ruleTestDocumentLabel(mapped), '[Тест] Договор.pdf (подготовка 40%)');
  assert.match(ruleTestDocumentWarning(mapped), /40%/);
  const failed = asRuleTestDocument({ ...source, phase: 'failed', status: 'FAILED', errorMessage: 'OCR недоступен' });
  assert.equal(ruleTestDocumentWarning(failed), 'OCR недоступен');
  assert.equal(isRuleTestDocumentProcessing(failed), false);
  assert.match(ruleTestDocumentLabel(failed), /ошибка подготовки/);
});

test('failed and unsupported documents never look ready or indefinitely processing', () => {
  for (const phase of ['failed', 'unsupported', 'uploaded']) {
    const document = { ...ready, phase, status: phase.toUpperCase() };
    assert.equal(isRuleTestDocumentReady(document), false);
    assert.equal(isRuleTestDocumentProcessing(document), false);
    assert.ok(ruleTestDocumentWarning(document));
    assert.doesNotMatch(ruleTestDocumentLabel(document), /подготовка \d+%/);
  }
  assert.equal(isRuleTestDocumentReady({ ...ready, phase: 'failed' }), false, 'terminal phase overrides an inconsistent old status');
  assert.equal(isRuleTestDocumentReady({ ...ready, phase: undefined }), true);
  assert.equal(ruleTestDocumentWarning(ready), null);
});

test('single-file validation reuses supported formats and limits while excluding ZIP', () => {
  assert.ok(RULE_TEST_UPLOAD_ACCEPT.includes('.pdf'));
  assert.ok(RULE_TEST_UPLOAD_ACCEPT.includes('.docx'));
  assert.ok(RULE_TEST_UPLOAD_ACCEPT.includes('.png'));
  assert.ok(!RULE_TEST_UPLOAD_ACCEPT.includes('.zip'));
  assert.match(validateRuleTestUpload({ name: 'contracts.ZIP', size: 30 }), /ZIP/);
  assert.match(validateRuleTestUpload({ name: 'contract.pdf', size: 0 }), /пустой/);
  assert.match(validateRuleTestUpload({ name: 'contract.pdf', size: MAX_FILE_BYTES + 1 }), /100 МБ/);
  assert.ok(validateRuleTestUpload({ name: 'contract.exe', size: 30 }));
  assert.equal(validateRuleTestUpload({ name: 'contract.PDF', size: MAX_FILE_BYTES }), null);
});
