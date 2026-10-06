import { documentInfo, statusLabels } from './mock-data';
import type { Finding, ReviewStatus } from './types';

export function downloadReport(name: string, items: Finding[], statuses: Record<number, ReviewStatus>) {
  const quote = (text: string | number) => `"${String(text).replaceAll('"', '""')}"`;
  const rows = [
    ['Документ', name], ['Режим', 'Демонстрационные данные; автоматический анализ не выполнялся'],
    ['Страниц', documentInfo.pages], [],
    ['№', 'Уровень', 'Замечание', 'Описание', 'Пункт', 'Страница', 'Статус', 'Комментарий к проверке'],
    ...items.map(f => [f.id, {critical:'Критический',warning:'Требует внимания',low:'Низкий риск',ok:'Без замечаний'}[f.severity], f.title, f.description, f.clause, f.page, statusLabels[statuses[f.id] ?? 'unseen'], f.recommendation]),
  ];
  // UTF-8 BOM and semicolons keep Russian text readable in spreadsheet applications.
  const blob = new Blob(['\uFEFF', rows.map(row => row.map(quote).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name.replace(/\.pdf$/i, '')} — отчёт.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
