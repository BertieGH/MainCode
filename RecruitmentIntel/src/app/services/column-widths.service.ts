import { Injectable } from '@angular/core';

const PREFIX = 'colWidths:';

@Injectable({ providedIn: 'root' })
export class ColumnWidthsService {
  load(tableKey: string): Record<string, number> {
    try {
      const raw = localStorage.getItem(PREFIX + tableKey);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return typeof parsed === 'object' && parsed ? parsed : {};
    } catch {
      return {};
    }
  }

  save(tableKey: string, widths: Record<string, number>): void {
    try {
      localStorage.setItem(PREFIX + tableKey, JSON.stringify(widths));
    } catch {
      // localStorage full or unavailable — silent fail.
    }
  }

  reset(tableKey: string): void {
    try {
      localStorage.removeItem(PREFIX + tableKey);
    } catch {
      // ignore
    }
  }
}
