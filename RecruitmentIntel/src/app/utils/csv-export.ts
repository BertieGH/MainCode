export interface CsvColumn<T> {
  header: string;
  value: (row: T) => unknown;
}

function escapeCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  let s: string;
  if (Array.isArray(value)) {
    s = value.join('; ');
  } else if (value instanceof Date) {
    s = value.toISOString();
  } else if (typeof value === 'object') {
    s = JSON.stringify(value);
  } else {
    s = String(value);
  }
  if (/[",\r\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

export function downloadCsv<T>(filename: string, columns: CsvColumn<T>[], rows: T[]): void {
  const header = columns.map(c => escapeCell(c.header)).join(',');
  const body = rows.map(r => columns.map(c => escapeCell(c.value(r))).join(',')).join('\r\n');
  const csv = '﻿' + header + (body ? '\r\n' + body : '');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = filename.endsWith('.csv') ? filename : `${filename}-${stamp}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
