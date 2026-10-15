import { CommonModule } from '@angular/common';
import {
  Component, ElementRef, EventEmitter, HostListener, Input, Output, TemplateRef,
  computed, inject, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { SortState, SortableDirective } from './sortable';
import {
  ActionTally, ColumnDef, RowAction, SavedView, distinctValues, loadView,
  matchesSearch, passesFilters, saveView, tally, toggleColumn, visibleColumns,
} from './table-view';

/** What a cell template receives. */
export interface CellContext {
  $implicit: unknown;
  column: ColumnDef;
  value: unknown;
}

/** A bulk action, with the selection it will and will not touch. */
export interface BulkRun {
  action: RowAction;
  rows: unknown[];
  skipped: unknown[];
}

/**
 * One table, with the columns the reader chose.
 *
 * Built because two screens hit the same wall from opposite sides: the account
 * list showed nine fixed columns when a rep wanted three, and contacts have
 * twenty fields worth showing and no screen wide enough. A fixed set cannot
 * serve both, and the right set changes with whatever stage somebody is
 * working at.
 *
 * Five things it does that a plain `<table>` does not:
 *
 * * **Refine view** — one collapsible row holding scope, search, the column
 *   dropdown and whatever actions the screen supplies. Expand, apply, collapse,
 *   and the table has the height back.
 * * **Choose columns from a dropdown**, grouped, remembered per table.
 * * **Resize by dragging**, remembered too.
 * * **Filter on any visible column** — text for free text, a dropdown of the
 *   values actually present for the rest.
 * * **Select rows and act on them in bulk**, running on what it can and
 *   reporting the rest.
 *
 * Rows are rendered by the caller through a template, so this stays a layout
 * component and never learns what an account or a contact is.
 */
@Component({
  selector: 'app-data-table',
  standalone: true,
  imports: [CommonModule, FormsModule, SortableDirective],
  template: `
    <div class="bar" [class.open]="panelOpen()">
      <button type="button" class="disc" (click)="panelOpen.set(!panelOpen())"
              [attr.aria-expanded]="panelOpen()">
        <span class="chev">›</span><strong>Refine view</strong>
      </button>
      <!-- Scope leads the summary. With the picker inside a collapsed panel,
           this is the one fact you cannot infer from the rows in front of you. -->
      <span class="summary">
        <span class="pill scope" *ngIf="scopeLabel">{{ scopeLabel }}</span>
        {{ shown().length }} of {{ columns.length }} columns
        <span class="pill" *ngIf="activeFilters()">{{ activeFilters() }} filter{{ activeFilters() === 1 ? '' : 's' }}</span>
        <span class="pill" *ngIf="query.trim()">search</span>
      </span>
      <span class="spacer"></span>
      <span class="count">
        {{ visible().length }}<span *ngIf="visible().length !== rows.length"> of {{ rows.length }}</span>
        {{ countNoun(rows.length) }}
      </span>
    </div>

    <div class="panel" [hidden]="!panelOpen()">
      <!-- The screen's own scope control — a list picker, a date range. The
           table never learns what it is. -->
      <ng-container *ngIf="scope" [ngTemplateOutlet]="scope"></ng-container>
      <span class="vr" *ngIf="scope"></span>

      <span class="search">
        <span class="ico">⌕</span>
        <input [(ngModel)]="query" (ngModelChange)="touch()"
               [attr.aria-label]="'Search ' + noun" placeholder="Search">
      </span>

      <span class="dd">
        <button type="button" class="btn" (click)="colsOpen.set(!colsOpen())"
                [attr.aria-expanded]="colsOpen()">
          Columns {{ shown().length }}/{{ columns.length }} ▾
        </button>
        <div class="menu" [hidden]="!colsOpen()">
          <div class="mhead">
            <button type="button" class="btn ghost" (click)="showAll()">All</button>
            <button type="button" class="btn ghost" (click)="showDefaults()">Essentials</button>
          </div>
          <ng-container *ngFor="let g of grouped()">
            <div class="grp" *ngIf="g.name">{{ g.name }}</div>
            <label class="pick" *ngFor="let c of g.cols">
              <input type="checkbox" [checked]="isShown(c)"
                     (change)="setShown(c, $any($event.target).checked)">
              {{ c.label }}
            </label>
          </ng-container>
        </div>
      </span>

      <span class="vr"></span>
      <button type="button" class="btn" (click)="clearFilters()"
              [disabled]="!activeFilters() && !query.trim()">Clear filters</button>
      <!-- Screen-specific buttons: export, import, whatever the page owns. -->
      <ng-container *ngIf="tools" [ngTemplateOutlet]="tools"></ng-container>
      <span class="spacer"></span>
      <button type="button" class="btn ghost" (click)="reset()">Reset layout</button>
    </div>

    <!-- Only with a selection, or while an action runs: a button is never
         present unless it can act. While one runs, every action is disabled —
         the running one shows it is working, and a second click cannot fire it
         twice. -->
    <div class="selbar" [hidden]="!picked.size && !busyKey">
      <ng-container *ngIf="picked.size; else workingOnly">
        <span class="n">{{ picked.size }} selected</span>
        <button type="button" class="btn" *ngFor="let t of tallies()"
                [disabled]="!t.eligible || !!busyKey" (click)="runBulk(t)"
                [class.busy]="busyKey === t.action.key"
                [title]="bulkHint(t)">
          <ng-container *ngIf="busyKey === t.action.key; else idle">
            {{ busyText || t.action.label }}
          </ng-container>
          <ng-template #idle>{{ t.action.label }}<span class="sub">{{ t.eligible }}</span></ng-template>
        </button>
        <span class="spacer"></span>
        <button type="button" class="btn ghost" (click)="clearSelection()">Clear</button>
      </ng-container>
      <!-- Run from a row's menu, with nothing selected: still say it is working. -->
      <ng-template #workingOnly>
        <span class="btn busy working" aria-live="polite">{{ busyText || 'Working…' }}</span>
      </ng-template>
    </div>


    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th class="selcol" *ngIf="selectable">
              <input type="checkbox" [checked]="allPicked()"
                     [indeterminate]="somePicked()" (change)="toggleAll($any($event.target).checked)"
                     aria-label="Select every row on screen">
            </th>
            <th *ngFor="let c of shown()" [style.width.px]="widthOf(c)"
                [class.mono]="c.numeric">
              <span [appSortable]="c.key" [state]="sort" (sortChange)="sortChange.emit($event)">
                {{ c.label }}
              </span>
              <span class="grip" (mousedown)="startResize($event, c)"
                    (touchstart)="startResize($event, c)"
                    [attr.aria-label]="'Resize ' + c.label"></span>
            </th>
            <th class="actcol" *ngIf="rowActions.length">Actions</th>
          </tr>
          <tr class="filters">
            <th class="selcol" *ngIf="selectable"></th>
            <th *ngFor="let c of shown()">
              <ng-container [ngSwitch]="c.filter ?? 'text'">
                <select *ngSwitchCase="'enum'" class="fin" [ngModel]="filters[c.key] ?? ''"
                        (ngModelChange)="setFilter(c.key, $event)"
                        [attr.aria-label]="'Filter by ' + c.label">
                  <option value="">any</option>
                  <option *ngFor="let v of options(c)" [value]="v">{{ v }}</option>
                </select>
                <span *ngSwitchCase="'none'"></span>
                <input *ngSwitchDefault class="fin" [ngModel]="filters[c.key] ?? ''"
                       (ngModelChange)="setFilter(c.key, $event)"
                       [attr.aria-label]="'Filter by ' + c.label" placeholder="filter">
              </ng-container>
            </th>
            <th class="actcol" *ngIf="rowActions.length"></th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of visible()" [class.picked]="isPicked(row)">
            <td class="selcol" *ngIf="selectable">
              <input type="checkbox" [checked]="isPicked(row)"
                     (change)="togglePick(row, $any($event.target).checked)"
                     [attr.aria-label]="'Select ' + label(row)">
            </td>
            <td *ngFor="let c of shown()" [class.mono]="c.numeric">
              <ng-container *ngTemplateOutlet="cell;
                context: {$implicit: row, column: c, value: read(row, c)}"></ng-container>
            </td>
            <td class="actcol" *ngIf="rowActions.length">
              <!-- Icon-only, so each carries an accessible name: the glyph means
                   nothing to a screen reader. -->
              <button type="button" class="iconbtn" (click)="open.emit(row)"
                      [title]="'Open ' + label(row)" [attr.aria-label]="'Open ' + label(row)"
                      *ngIf="openable">↗</button>
              <button type="button" class="iconbtn" (click)="openMenu($event, row)"
                      [title]="'More actions for ' + label(row)"
                      [attr.aria-label]="'More actions for ' + label(row)">⋯</button>
            </td>
          </tr>
          <tr *ngIf="!visible().length">
            <td class="empty"
                [attr.colspan]="shown().length + (selectable ? 1 : 0) + (rowActions.length ? 1 : 0)">
              {{ rows.length ? 'Nothing matches that.' : emptyText }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- One menu, repositioned per row. Rendered per-row it would be clipped
         by the table's own horizontal scroll. -->
    <div class="rowmenu" [hidden]="!menuRow()" [style.left.px]="menuAt().x"
         [style.top.px]="menuAt().y">
      <button type="button" *ngFor="let a of rowMenu()"
              [class.danger]="a.action.danger" [disabled]="!a.enabled || !!busyKey"
              [title]="a.enabled ? '' : (a.action.why ?? '')"
              (click)="runRow(a.action)">
        {{ a.action.label }}<span class="skipnote" *ngIf="!a.enabled"> — {{ a.action.why }}</span>
      </button>
    </div>
  `,
  styles: [
    `
      .bar{display:flex;align-items:center;gap:10px;padding:9px 2px;flex-wrap:wrap}
      .bar.open{border-bottom:1px solid var(--line);margin-bottom:0}
      .chev{display:inline-block;transition:transform .15s;font-size:.8rem;color:var(--muted)}
      .bar.open .chev{transform:rotate(90deg)}
      .disc{display:flex;align-items:center;gap:7px;background:none;border:none;
            cursor:pointer;font:inherit;color:inherit;padding:2px 0}
      .disc strong{font-size:.86rem}
      .summary{color:var(--muted);font-size:.79rem}
      .pill{background:var(--line);border-radius:9px;padding:1px 7px;
            font-size:.72rem;margin-left:5px}
      .pill.scope{background:var(--accent-soft,var(--line));margin-left:0;margin-right:3px}
      .spacer{flex:1}
      .count{color:var(--muted);font-size:.79rem}

      .panel{display:flex;gap:9px;align-items:center;flex-wrap:wrap;
             padding:10px 2px;border-bottom:1px solid var(--line);margin-bottom:8px}
      .vr{width:1px;height:22px;background:var(--line)}
      .search{position:relative;display:inline-flex;align-items:center}
      .search .ico{position:absolute;left:8px;color:var(--muted);font-size:.8rem}
      .search input{font:inherit;font-size:.79rem;padding:5px 9px 5px 24px;width:210px;
                    border:1px solid var(--line);border-radius:6px;
                    background:var(--card,#fff);color:inherit}
      .btn.small,.btn{font-size:.78rem;padding:5px 11px}
      .btn .sub{opacity:.65;font-size:.72rem;margin-left:4px}

      .dd{position:relative;display:inline-block}
      .menu{position:absolute;z-index:40;top:calc(100% + 5px);left:0;min-width:225px;
            max-height:300px;overflow:auto;background:var(--card,#fff);
            border:1px solid var(--line);border-radius:8px;padding:7px;
            box-shadow:0 8px 28px rgba(0,0,0,.18)}
      .menu .mhead{display:flex;gap:6px;padding:2px 4px 7px;
                   border-bottom:1px solid var(--line);margin-bottom:5px}
      .grp{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;
           color:var(--muted);padding:6px 6px 2px}
      .pick{display:flex;align-items:center;gap:7px;font-size:.79rem;
            cursor:pointer;padding:4px 6px;border-radius:5px}
      .pick:hover{background:var(--line)}

      .selbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
              padding:8px 10px;margin-bottom:8px;border-radius:7px;
              background:var(--accent-soft,var(--line))}
      .selbar.result{background:transparent;border:1px solid var(--line)}
      .selbar .n{font-size:.81rem;font-weight:600}
      .selbar .working{cursor:default;border-color:transparent;background:transparent}
      .skipnote{color:var(--warn);font-size:.73rem}

      .table-wrap{overflow-x:auto}
      table.data{table-layout:fixed;width:100%}
      th{position:relative}
      th .grip{position:absolute;right:0;top:0;height:100%;width:7px;
               cursor:col-resize;touch-action:none}
      th .grip:hover{background:var(--line)}
      th.selcol,td.selcol{width:38px;text-align:center;padding-left:10px;padding-right:2px}
      /* Pinned and never hidden: turning it off would strand every per-row
         operation. */
      th.actcol,td.actcol{width:86px;text-align:right;position:sticky;right:0;
                          background:var(--card,#fff)}
      tr.filters th{padding-top:0;padding-bottom:6px;font-weight:400}
      .fin{width:100%;font:inherit;font-size:.72rem;padding:2px 5px;
           border:1px solid var(--line);border-radius:5px;
           background:var(--card,#fff);color:inherit}
      td{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      tr.picked{background:var(--accent-soft,var(--line))}
      .empty{text-align:center;padding:26px;color:var(--muted)}
      .iconbtn{border:1px solid transparent;background:none;cursor:pointer;
               border-radius:5px;padding:2px 5px;color:var(--muted)}
      .iconbtn:hover{background:var(--line);color:inherit}

      .rowmenu{position:fixed;z-index:60;min-width:200px;background:var(--card,#fff);
               border:1px solid var(--line);border-radius:8px;padding:5px;
               box-shadow:0 10px 30px rgba(0,0,0,.2)}
      .rowmenu button{display:block;width:100%;text-align:left;border:none;
                      background:none;font:inherit;font-size:.79rem;padding:6px 9px;
                      border-radius:5px;cursor:pointer;color:inherit}
      .rowmenu button:hover:not(:disabled){background:var(--line)}
      .rowmenu button:disabled{color:var(--muted);cursor:default}
      .rowmenu button.danger{color:var(--critical)}
    `,
  ],
})
export class DataTableComponent {
  @Input({ required: true }) table = '';
  @Input({ required: true }) columns: ColumnDef[] = [];
  @Input({ required: true }) set data(rows: unknown[]) {
    this.rows = rows ?? [];
    // Selection is by identity, and the rows are new objects after a reload —
    // so anything no longer present is dropped rather than silently acted on.
    const ids = new Set(this.rows.map((r) => this.idOf(r)));
    for (const id of [...this.picked]) if (!ids.has(id)) this.picked.delete(id);
    this.touch();
  }
  @Input({ required: true }) cell!: TemplateRef<CellContext>;
  /** The screen's scope control — a list picker, say. Rendered first in the panel. */
  @Input() scope: TemplateRef<unknown> | null = null;
  /** Extra buttons for the panel: export, import, anything the page owns. */
  @Input() tools: TemplateRef<unknown> | null = null;
  /** Shown as a pill in the collapsed bar, so scope survives collapsing. */
  @Input() scopeLabel = '';
  @Input() sort: SortState = { field: null, direction: 'asc' };
  @Input() noun = 'rows';
  @Input() emptyText = 'Nothing here yet.';
  @Input() selectable = false;
  @Input() openable = true;
  @Input() rowActions: RowAction[] = [];
  /** Reads a stable id. Selection survives a refresh only if this is stable. */
  @Input() idOf: (row: any) => string = (r) => r?.id;
  /** Names a row in tooltips and aria labels. */
  @Input() label: (row: any) => string = (r) => r?.name ?? r?.full_name ?? 'row';
  /**
   * The action running now, by key. While set, every bulk button and row-menu
   * item is disabled and that action's button shows it is working — so it
   * cannot be clicked twice, and nothing else can start underneath it.
   */
  @Input() busyKey: string | null = null;
  /** What the working button reads — "Researching 3 of 8…". */
  @Input() busyText = '';

  @Output() sortChange = new EventEmitter<SortState>();
  @Output() open = new EventEmitter<unknown>();
  @Output() bulk = new EventEmitter<BulkRun>();
  @Output() rowAction = new EventEmitter<{ action: RowAction; row: unknown }>();

  private host = inject(ElementRef<HTMLElement>);

  /**
   * Close the row menu and the Columns dropdown on a click anywhere else.
   *
   * Without this a menu stayed open until one of its own items was chosen —
   * there was no way to change your mind. The row menu's opener stops
   * propagation, so the click that opens it never arrives here; the Columns
   * button does not, so clicks inside `.dd` are ignored instead.
   */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as Node | null;
    const root = this.host.nativeElement as HTMLElement;
    const dd = root.querySelector('.dd');
    const menu = root.querySelector('.rowmenu');
    if (this.colsOpen() && dd && target && !dd.contains(target)) this.colsOpen.set(false);
    if (this.menuRow() && menu && target && !menu.contains(target)) this.menuRow.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.colsOpen.set(false);
    this.menuRow.set(null);
  }

  /** The row menu is fixed-position; left open while the page scrolls, it
   *  would drift away from the row it belongs to. */
  @HostListener('window:scroll')
  onScroll(): void {
    if (this.menuRow()) this.menuRow.set(null);
  }

  rows: unknown[] = [];
  filters: Record<string, string> = {};
  query = '';
  picked = new Set<string>();
  panelOpen = signal(false);
  colsOpen = signal(false);
  menuRow = signal<unknown | null>(null);
  menuAt = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  /**
   * Bumped when anything the derived lists depend on changes.
   *
   * `rows`, `filters` and `query` are plain properties — nothing observes them.
   * The computeds read this to know they are stale. Calling a method from the
   * template instead builds a new array every change-detection pass and locks
   * the page up; that already happened once on the import screen.
   */
  private revision = signal(0);
  private view = signal<SavedView>({ hidden: [], shown: [], widths: {}, order: [] });
  private loaded = false;

  ngOnChanges(): void {
    if (!this.loaded && this.table) {
      this.view.set(loadView(this.table));
      this.loaded = true;
    }
  }

  /** "1 list", not "1 lists". */
  countNoun(n: number): string {
    return n === 1 ? this.noun.replace(/s$/, '') : this.noun;
  }

  touch(): void {
    this.revision.update((n) => n + 1);
  }

  shown = computed(() => {
    this.revision();
    return visibleColumns(this.columns, this.view());
  });

  visible = computed(() => {
    this.revision();
    const cols = visibleColumns(this.columns, this.view());
    return this.rows.filter(
      (r) => passesFilters(r, cols, this.filters) && matchesSearch(r, cols, this.query),
    );
  });

  activeFilters = computed(() => {
    this.revision();
    return Object.values(this.filters).filter((v) => (v ?? '').trim()).length;
  });

  /** The column dropdown, in the groups the caller declared. */
  grouped = computed(() => {
    this.revision();
    const out: { name: string; cols: ColumnDef[] }[] = [];
    for (const c of this.columns) {
      const name = (c as { group?: string }).group ?? '';
      const last = out[out.length - 1];
      if (last && last.name === name) last.cols.push(c);
      else out.push({ name, cols: [c] });
    }
    return out;
  });

  tallies = computed((): ActionTally[] => {
    this.revision();
    const sel = this.selectedRows();
    return this.rowActions.filter((a) => a.bulk !== false).map((a) => tally(a, sel));
  });

  rowMenu = computed(() => {
    this.revision();
    const row = this.menuRow();
    return this.rowActions
      .filter((a) => a.row !== false)
      .map((a) => ({ action: a, enabled: row ? (a.can ? a.can(row) : true) : false }));
  });

  // --- reading -----------------------------------------------------------
  read(row: unknown, col: ColumnDef): unknown {
    return col.value ? col.value(row) : (row as Record<string, unknown>)?.[col.key];
  }
  options(col: ColumnDef): string[] {
    return distinctValues(this.rows, col);
  }
  isShown(col: ColumnDef): boolean {
    return this.shown().some((c) => c.key === col.key);
  }
  widthOf(col: ColumnDef): number | null {
    return this.view().widths[col.key] ?? col.width ?? null;
  }

  // --- columns -----------------------------------------------------------
  setShown(col: ColumnDef, visible: boolean): void {
    this.view.update((v) => toggleColumn(v, col.key, visible));
    this.persist();
  }
  showAll(): void {
    this.view.update((v) => ({ ...v, hidden: [], shown: this.columns.map((c) => c.key) }));
    this.persist();
  }
  showDefaults(): void {
    this.view.update((v) => ({
      ...v,
      shown: this.columns.filter((c) => c.defaultVisible !== false).map((c) => c.key),
      hidden: this.columns.filter((c) => c.defaultVisible === false).map((c) => c.key),
    }));
    this.persist();
  }

  // --- filters -----------------------------------------------------------
  setFilter(key: string, value: string): void {
    this.filters = { ...this.filters, [key]: value };
    this.touch();
  }
  clearFilters(): void {
    this.filters = {};
    this.query = '';
    this.touch();
  }

  // --- selection ---------------------------------------------------------
  selectedRows(): unknown[] {
    return this.rows.filter((r) => this.picked.has(this.idOf(r)));
  }
  isPicked(row: unknown): boolean {
    return this.picked.has(this.idOf(row));
  }
  togglePick(row: unknown, on: boolean): void {
    on ? this.picked.add(this.idOf(row)) : this.picked.delete(this.idOf(row));
    this.touch();
  }
  allPicked(): boolean {
    const v = this.visible();
    return v.length > 0 && v.every((r) => this.picked.has(this.idOf(r)));
  }
  somePicked(): boolean {
    return this.visible().some((r) => this.picked.has(this.idOf(r))) && !this.allPicked();
  }
  /** Takes what is on screen. Ticking the header after filtering to six must
   *  never quietly select all forty. */
  toggleAll(on: boolean): void {
    for (const r of this.visible()) {
      on ? this.picked.add(this.idOf(r)) : this.picked.delete(this.idOf(r));
    }
    this.touch();
  }
  clearSelection(): void {
    this.picked.clear();
    this.touch();
  }

  // --- acting ------------------------------------------------------------
  bulkHint(t: ActionTally): string {
    if (!t.eligible) return `None of the selection can: ${t.action.why ?? 'not eligible'}`;
    const skipped = t.blocked ? ` · ${t.blocked} skipped: ${t.action.why}` : '';
    return `Runs on ${t.eligible} of ${this.picked.size}${skipped}`;
  }

  runBulk(t: ActionTally): void {
    // Only splits the selection. The screen confirms, runs and reports — this
    // used to announce "sent N" before the confirmation had even been answered.
    const can = t.action.can ?? (() => true);
    const sel = this.selectedRows();
    this.bulk.emit({
      action: t.action,
      rows: sel.filter((r) => can(r)),
      skipped: sel.filter((r) => !can(r)),
    });
  }

  openMenu(event: MouseEvent, row: unknown): void {
    event.stopPropagation();
    const r = (event.currentTarget as HTMLElement).getBoundingClientRect();
    // Flipped up near the bottom so the last row's menu is never off-screen.
    const below = window.innerHeight - r.bottom > 240;
    this.menuAt.set({
      x: Math.max(8, r.right - 200),
      y: below ? r.bottom + 4 : Math.max(8, r.top - 4 - 240),
    });
    this.menuRow.set(row);
    this.touch();
  }

  runRow(action: RowAction): void {
    const row = this.menuRow();
    this.menuRow.set(null);
    if (row) this.rowAction.emit({ action, row });
  }

  // --- widths ------------------------------------------------------------
  startResize(event: MouseEvent | TouchEvent, col: ColumnDef): void {
    event.preventDefault();
    const point = (e: MouseEvent | TouchEvent) =>
      'touches' in e ? e.touches[0]?.clientX ?? 0 : (e as MouseEvent).clientX;
    const startX = point(event);
    const header = (event.target as HTMLElement).parentElement;
    const startWidth = header?.getBoundingClientRect().width ?? col.width ?? 120;

    const move = (e: MouseEvent | TouchEvent) => {
      const next = Math.min(900, Math.max(60, startWidth + point(e) - startX));
      this.view.update((v) => ({ ...v, widths: { ...v.widths, [col.key]: next } }));
      this.touch();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      window.removeEventListener('touchmove', move);
      window.removeEventListener('touchend', up);
      this.persist();
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    window.addEventListener('touchmove', move);
    window.addEventListener('touchend', up);
  }

  reset(): void {
    this.view.set({ hidden: [], shown: [], widths: {}, order: [] });
    this.filters = {};
    this.query = '';
    this.persist();
  }

  private persist(): void {
    this.touch();
    if (this.table) saveView(this.table, this.view());
  }
}
