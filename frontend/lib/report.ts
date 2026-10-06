import { documentInfo, statusLabels } from './mock-data';
import type { Finding, ReviewStatus } from './types';

function quoteCell(value: string | number): string {
  const text = String(value);
  // CSV quoting does not stop spreadsheet formulas. Keep user-controlled cells
  // as text, including formulas concealed behind leading whitespace or controls.
  const formulaLike = typeof value === 'string' && /^(?:[\s\u0000-\u001f]*[=+\-@]|[\t\r\n])/u.test(text);
  const safeText = formulaLike ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
}

export function buildReportCsv(name: string, items: Finding[], statuses: Record<number, ReviewStatus>): string {
  const rows = [
    ['Документ', name], ['Режим', 'Демонстрационные данные; автоматический анализ не выполнялся'],
    ['Страниц', documentInfo.pages], [],
    ['№', 'Уровень', 'Замечание', 'Описание', 'Пункт', 'Страница', 'Статус', 'Комментарий к проверке'],
    ...items.map(f => [f.id, {critical:'Критический',warning:'Требует внимания',low:'Низкий риск',ok:'Без замечаний'}[f.severity], f.title, f.description, f.clause, f.page, statusLabels[statuses[f.id] ?? 'unseen'], f.recommendation]),
  ];
  // UTF-8 BOM and semicolons keep Russian text readable in spreadsheet applications.
  return `\uFEFF${rows.map(row => row.map(quoteCell).join(';')).join('\r\n')}`;
}

export function downloadReport(name: string, items: Finding[], statuses: Record<number, ReviewStatus>) {
  const blob = new Blob([buildReportCsv(name, items, statuses)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name.replace(/\.pdf$/i, '')} — отчёт.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
