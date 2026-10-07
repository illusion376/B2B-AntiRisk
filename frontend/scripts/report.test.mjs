import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadLib } from './load-lib.mjs';

const { buildReportCsv } = await loadLib('report');

const finding = (overrides = {}) => ({
  id: 1, title: 'Неограниченная ответственность', description: 'Штраф не ограничен', severity: 'critical',
  category: 'Ответственность', clause: '6.2', page: 18, quote: '', recommendation: 'Ограничить ответственность',
  ...overrides,
});

const rows = csv => csv.replace(/^﻿/, '').split('\r\n');

test('CSV начинается с BOM и разделяет строки CRLF — Excel открывает кириллицу', () => {
  const csv = buildReportCsv('Проект контракта.pdf', [finding()], {});
  assert.ok(csv.startsWith('﻿'));
  assert.ok(rows(csv).length > 5);
});

test('ячейки в кавычках через «;», кавычки внутри удваиваются', () => {
  const csv = buildReportCsv('Договор "Альфа".pdf', [finding({ title: 'Пункт "6.2"' })], {});
  assert.equal(rows(csv)[0], '"Документ";"Договор ""Альфа"".pdf"');
  assert.ok(csv.includes('"Пункт ""6.2"""'));
});

test('строка замечания: уровень, пункт, страница и статус по умолчанию', () => {
  const line = rows(buildReportCsv('doc.pdf', [finding()], {})).at(-1);
  assert.equal(line, '"1";"Критический";"Неограниченная ответственность";"Штраф не ограничен";"6.2";"18";"Не просмотрено";"Ограничить ответственность"');
});

test('в отчёт попадает текущий статус проверки', () => {
  const line = rows(buildReportCsv('doc.pdf', [finding()], { 1: 'accepted' })).at(-1);
  assert.ok(line.includes('"Принято"'));
});

test('формулы в пользовательских полях экранируются апострофом', () => {
  for (const formula of ['=HYPERLINK("http://evil")', '+7 (999)', '-1+2', '@SUM(A1)']) {
    const line = rows(buildReportCsv('doc.pdf', [finding({ title: formula })], {})).at(-1);
    assert.ok(line.includes(`"'${formula.replaceAll('"', '""')}"`), formula);
  }
});

test('формула за пробелами и управляющими символами тоже экранируется', () => {
  const csv = buildReportCsv('  =cmd|calc', [finding({ description: '\t=1+1' })], {});
  assert.equal(rows(csv)[0], `"Документ";"'  =cmd|calc"`);
  assert.ok(csv.includes(`"'\t=1+1"`));
});

test('числа и обычный текст не изменяются', () => {
  const line = rows(buildReportCsv('doc.pdf', [finding({ title: 'Срок оплаты — 30 дней' })], {})).at(-1);
  assert.ok(line.startsWith('"1";'));
  assert.ok(line.includes('"Срок оплаты — 30 дней"'));
});
