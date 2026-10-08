import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ImportField, ImportMapping, ImportReport, ListsService } from '../core/lists.service';
import { apiError } from '../shared/api-error';

/**
 * CSV import — upload, map, dry run, commit.
 *
 * The dry run is not a preview built from different code. It calls the same
 * endpoint with `dry_run=true`, which runs the identical resolution and then
 * rolls back. What you see is the decision that will be taken, not an estimate
 * of it.
 *
 * Commit is deliberately unreachable until a dry run has been seen.
 */
@Component({
  selector: 'app-csv-import',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="card">
      <!-- step 1 -->
      <div *ngIf="step() === 1">
        <h3>1 · Choose a file</h3>
        <p class="row-sub">Headers are matched automatically; you confirm the mapping next.</p>
        <input type="file" accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
               (change)="onFile($event)" class="field"
               style="margin-top:12px;padding:9px;">
        <p class="row-sub" style="margin-top:6px;">CSV or Excel (.xlsx or .xls).</p>
      </div>

      <!-- step 2 -->
      <div *ngIf="step() === 2 && mapping() as m">
        <h3>2 · Confirm the mapping</h3>

        <!-- What will go wrong, said before the import rather than after. The
             last failure was silent: a file imported one company and zero
             contacts, and nothing on screen said the contact columns had been
             dropped. -->
        <div class="warn-box" *ngIf="m.warnings.length">
          <div *ngFor="let w of m.warnings" class="warn-line">{{ w }}</div>
        </div>

        <p class="row-sub">
          {{ m.headers.length }} columns found · this file looks like
          <strong>{{ m.predicted_grain === 'contact' ? 'people' : 'companies' }}</strong>.
          Anything left unmapped is ignored.
        </p>

        <div class="mapsec" *ngFor="let group of groups()">
          <h4>{{ group.title }}</h4>
          <p class="row-sub">{{ group.blurb }}</p>
          <div class="map-grid">
            <label *ngFor="let f of group.fields">
              <span class="fname">
                {{ f.label }}<span class="req" *ngIf="f.required"> *</span>
              </span>
              <select class="field" [(ngModel)]="chosen[f.key]"
                      (ngModelChange)="onMappingChanged()"
                      [ngModelOptions]="{standalone:true}">
                <option [ngValue]="null">— not imported —</option>
                <option *ngFor="let h of m.headers" [ngValue]="h">{{ h }}</option>
              </select>
              <!-- The first row's value, so a company name sitting in the
                   domain field is visible before it is written. -->
              <span class="sample" *ngIf="sample(m, chosen[f.key]) as v">
                e.g. {{ v }}
              </span>
              <span class="row-sub hint" *ngIf="f.hint">{{ f.hint }}</span>
            </label>
          </div>
        </div>

        <div class="mapsec" *ngIf="ignoredHeaders().length">
          <h4>Not imported</h4>
          <p class="row-sub">
            These columns are in the file and no field claims them. They are
            dropped.
          </p>
          <div class="chips">
            <span class="chip" *ngFor="let h of ignoredHeaders()">{{ h }}</span>
          </div>
        </div>

        <div style="display:flex;gap:10px;margin-top:16px;">
          <button class="btn btn-primary" (click)="dryRun()"
                  [disabled]="busy() || !chosen['name'] && !chosen['domain']">
            {{ busy() ? 'Checking…' : 'Dry run' }}
          </button>
          <button class="btn" (click)="reset()">Start over</button>
        </div>
        <p class="row-sub" style="margin-top:10px;" *ngIf="!chosen['name'] && !chosen['domain']">
          Map at least a company name or a domain — a row with neither cannot be resolved.
        </p>
        <p class="row-sub warn-line" style="margin-top:10px;" *ngIf="noContact()">
          No contact column is mapped. This will import companies only, and
          enrichment will have nobody to find addresses for.
        </p>
      </div>

      <!-- step 3 -->
      <div *ngIf="step() === 3 && report() as r">
        <h3>3 · {{ r.committed ? 'Imported' : 'Dry run — nothing written yet' }}</h3>

        <div class="counts">
          <span *ngFor="let c of countEntries(r)" class="badge" [ngClass]="countClass(c[0])">
            {{ c[1] }} {{ label(c[0]) }}
          </span>
        </div>

        <div class="table-wrap" style="margin-top:14px;max-height:280px;overflow:auto;">
          <table class="data">
            <thead>
              <tr><th>Row</th><th>Company</th><th>Domain</th><th>Outcome</th><th>Why</th></tr>
            </thead>
            <tbody>
              <tr *ngFor="let row of r.rows">
                <td class="mono">{{ row.row_number }}</td>
                <td>{{ row.name || '—' }}</td>
                <td class="mono row-sub">{{ row.domain || '—' }}</td>
                <td><span class="badge" [ngClass]="countClass(row.outcome)">{{ label(row.outcome) }}</span></td>
                <td class="row-sub">{{ row.detail }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div style="display:flex;gap:10px;margin-top:16px;align-items:center;" *ngIf="!r.committed">
          <button class="btn btn-primary" (click)="commit()" [disabled]="busy()">
            {{ busy() ? 'Importing…'
               : 'Import ' + willWrite(r) + ' accounts'
                 + (willWriteContacts(r) ? ' · ' + willWriteContacts(r) + ' contacts' : '') }}
          </button>
          <button class="btn" (click)="reset()">Cancel</button>
          <span class="row-sub">Nothing has been written yet.</span>
        </div>

        <div style="display:flex;gap:10px;margin-top:16px;" *ngIf="r.committed">
          <button class="btn btn-primary" (click)="done()">Done</button>
        </div>
      </div>

      <p class="row-sub" style="color:var(--critical);margin-top:12px;" *ngIf="error()">
        {{ error() }}
      </p>
    </div>
  `,
  styles: [
    `
      .warn-box { border:1px solid var(--critical); border-radius:6px;
                  padding:9px 11px; margin:10px 0 4px; }
      .warn-line { color:var(--critical); font-size:.8rem; }
      .mapsec { margin-top:18px; }
      .mapsec h4 { font-size:.86rem; margin:0 0 2px; }
      .map-grid label { display:flex; flex-direction:column; gap:3px; }
      .fname { font-size:.78rem; font-weight:600; }
      .req { color:var(--critical); }
      .sample { font-size:.7rem; color:var(--muted); font-family:monospace;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .hint { font-size:.7rem; }
      .chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:5px; }
      .chip { border:1px solid var(--line); border-radius:10px;
              padding:1px 8px; font-size:.72rem; }
      h3 { font-size: .98rem; margin-bottom: 4px; }
      .map-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
      .map-grid label { display: flex; flex-direction: column; gap: 5px; font-size: .8rem; }
      .fname { font-family: 'IBM Plex Mono', monospace; font-size: .72rem; color: var(--muted); }
      .counts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
      @media (max-width: 700px) { .map-grid { grid-template-columns: 1fr; } }
    `,
  ],
})
export class CsvImportComponent {
  private api = inject(ListsService);

  @Input({ required: true }) listId!: string;
  @Output() finished = new EventEmitter<void>();

  fields = ['name', 'domain', 'industry', 'employee_count', 'hq_country', 'hq_region',
            'linkedin_url', 'funding_stage'];

  step = signal(1);
  mapping = signal<ImportMapping | null>(null);

  /**
   * The mapping view, computed once rather than on every change detection.
   *
   * These were methods called straight from `*ngFor`. Each returned a **new
   * array**, so `ngFor` saw a new identity every pass, re-rendered, and
   * scheduled another pass — the screen locked up and the tab stopped
   * responding. Anything an `*ngFor` iterates has to be a stored value with a
   * stable identity; a method that builds a list is a loop waiting to happen.
   */
  groups = signal<{ title: string; blurb: string; fields: ImportField[] }[]>([]);
  ignoredHeaders = signal<string[]>([]);
  noContact = signal(false);

  /** Split the fields by the record they land on. Called once per file. */
  private buildGroups(m: ImportMapping): void {
    this.groups.set(
      [
        {
          title: 'Company',
          blurb: 'One account per distinct company. Required to import anything.',
          fields: m.fields.filter((f) => f.entity === 'account'),
        },
        {
          title: 'Contact',
          blurb:
            'Map at least one of these for the file to be read as people. ' +
            'Without them it imports companies only.',
          fields: m.fields.filter((f) => f.entity === 'contact'),
        },
      ].filter((g) => g.fields.length),
    );
  }

  /**
   * Recompute what the current choices leave behind.
   *
   * Driven by `(ngModelChange)` because `chosen` is a plain object — nothing
   * watches it, and making it a signal would mean rebuilding the two-way
   * binding for fifteen selects to fix a list that changes on click.
   */
  onMappingChanged(): void {
    const m = this.mapping();
    if (!m) return;
    const claimed = new Set(Object.values(this.chosen).filter(Boolean));
    this.ignoredHeaders.set(m.headers.filter((h) => !claimed.has(h)));
    this.noContact.set(
      !m.fields.some((f) => f.entity === 'contact' && this.chosen[f.key]),
    );
  }

  /** The first row's value for a column, so a mis-mapping is visible.
   *
   *  Safe to call from the template: it returns a string, and a primitive
   *  compares by value rather than identity. */
  sample(m: ImportMapping, header: string | null | undefined): string | null {
    if (!header) return null;
    const value = m.sample_rows[0]?.[header];
    return value ? String(value).slice(0, 40) : null;
  }
  report = signal<ImportReport | null>(null);
  busy = signal(false);
  error = signal<string | null>(null);

  chosen: Record<string, string | null> = {};
  private file: File | null = null;

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file = input.files?.[0] ?? null;
    if (!this.file) return;

    this.busy.set(true);
    this.api.inspectCsv(this.listId, this.file).subscribe({
      next: (m) => {
        this.mapping.set(m);
        this.chosen = { ...m.suggested };
        this.buildGroups(m);
        this.onMappingChanged();
        this.step.set(2);
        this.busy.set(false);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Could not read that file.'));
      },
    });
  }

  dryRun(): void {
    this.run(true);
  }

  commit(): void {
    this.run(false);
  }

  private run(dry: boolean): void {
    if (!this.file) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.importCsv(this.listId, this.file, this.chosen, dry).subscribe({
      next: (r) => {
        this.report.set(r);
        this.step.set(3);
        this.busy.set(false);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiError(err, 'Import failed.'));
      },
    });
  }

  /** Only `created` and `merged` rows become list members. */
  /** Companies this import will write, as the server counted them.
   *
   *  Was `created + merged`, which are **account-grain outcomes**: on a
   *  contact-grain file every row reports a contact outcome instead, so the
   *  button read "Import 0 accounts" for a file that would create twenty-five
   *  of them. A preview that under-reports what a commit will do is worse than
   *  no preview — it is a reason not to press the button.
   */
  willWrite(r: ImportReport): number {
    return r.accounts_touched;
  }

  /** People this import will write, or 0 on a company file. */
  willWriteContacts(r: ImportReport): number {
    return (r.counts['contact_created'] ?? 0) + (r.counts['contact_updated'] ?? 0);
  }

  countEntries(r: ImportReport): [string, number][] {
    return Object.entries(r.counts);
  }

  label(outcome: string): string {
    return {
      created: 'new',
      merged: 'matched existing',
      duplicate_in_file: 'duplicate in file',
      already_in_list: 'already in list',
      skipped_no_name: 'skipped',
    }[outcome] ?? outcome;
  }

  countClass(outcome: string): string {
    return {
      created: 'badge-good',
      merged: 'badge-accent',
      duplicate_in_file: 'badge-warn',
      already_in_list: 'badge-neutral',
      skipped_no_name: 'badge-critical',
    }[outcome] ?? 'badge-neutral';
  }

  reset(): void {
    this.step.set(1);
    this.mapping.set(null);
    this.report.set(null);
    this.file = null;
    this.error.set(null);
  }

  done(): void {
    this.reset();
    this.finished.emit();
  }
}
