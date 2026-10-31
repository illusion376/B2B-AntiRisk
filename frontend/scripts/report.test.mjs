import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { reportFilename } = await loadLib('report');

test('uses server UTF-8 attachment filename ahead of its ASCII fallback', () => {
  assert.equal(reportFilename(`attachment; filename="report.docx"; filename*=UTF-8''${encodeURIComponent('Договор — отчёт.docx')}`), 'Договор — отчёт.docx');
});

test('ordinary filenames and semicolons inside quoted filenames are preserved', () => {
  assert.equal(reportFilename('attachment; filename="contract; report.pdf"'), 'contract; report.pdf');
  assert.equal(reportFilename('attachment; filename=report.csv'), 'report.csv');
});

test('malformed UTF-8 falls back to filename or requested report format', () => {
  assert.equal(reportFilename('attachment; filename="report.docx"; filename*=UTF-8\'\'%broken'), 'report.docx');
  assert.equal(reportFilename(null, 'report.json'), 'report.json');
});

test('server attachment filename cannot retain directories or control characters', () => {
  assert.equal(reportFilename('attachment; filename="../../report.pdf"'), 'report.pdf');
  assert.equal(reportFilename(`attachment; filename*=UTF-8''${encodeURIComponent('folder\\report\u0000.pdf')}`), 'report.pdf');
  assert.equal(reportFilename('attachment; filename=".."', 'report.csv'), 'report.csv');
});
