import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CsvImportComponent } from './csv-import.component';
import { ImportReport } from '../core/lists.service';

function report(
  counts: Record<string, number>,
  committed = false,
  over: Partial<ImportReport> = {},
): ImportReport {
  return {
    total_rows: Object.values(counts).reduce((a, b) => a + b, 0),
    committed,
    counts,
    rows: [],
    // What the server counts: distinct companies the import will touch. On an
    // account file it equals created + merged, which is why the button agreed
    // with itself for so long on the only files anyone tested.
    accounts_touched: (counts['created'] ?? 0) + (counts['merged'] ?? 0),
    grain: 'account',
    ...over,
  };
}

describe('CsvImportComponent', () => {
  let fixture: ComponentFixture<CsvImportComponent>;
  let cmp: CsvImportComponent;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CsvImportComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(CsvImportComponent);
    cmp = fixture.componentInstance;
    cmp.listId = 'list-1';
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  describe('willWrite', () => {
    it('counts only rows that become members', () => {
      // The number on the button has to be the number you get. Counting all
      // rows would promise five imports and deliver three.
      const r = report({
        created: 3,
        merged: 1,
        duplicate_in_file: 2,
        already_in_list: 4,
        skipped_no_name: 1,
      });
      expect(cmp.willWrite(r)).toBe(4);
    });

    it('is zero when every row is a duplicate or a skip', () => {
      expect(cmp.willWrite(report({ duplicate_in_file: 3, skipped_no_name: 2 }))).toBe(0);
    });

    it('handles absent keys without producing NaN', () => {
      expect(cmp.willWrite(report({}))).toBe(0);
    });
  });

  describe('outcome presentation', () => {
    it('gives every outcome a human label', () => {
      const outcomes = [
        'created', 'merged', 'duplicate_in_file', 'already_in_list', 'skipped_no_name',
      ];
      for (const o of outcomes) {
        expect(cmp.label(o)).not.toBe(o, `${o} fell through to the raw key`);
      }
    });

    it('falls back to the raw key rather than blank for an unknown outcome', () => {
      // A new server-side outcome should look odd, not invisible.
      expect(cmp.label('some_new_outcome')).toBe('some_new_outcome');
    });

    it('colours a skip as critical and a merge as accent', () => {
      expect(cmp.countClass('skipped_no_name')).toBe('badge-critical');
      expect(cmp.countClass('merged')).toBe('badge-accent');
      expect(cmp.countClass('created')).toBe('badge-good');
    });
  });

  describe('the dry run gate', () => {
    it('starts at step 1', () => {
      expect(cmp.step()).toBe(1);
    });

    it('a dry run does not mark the report committed', () => {
      cmp['file'] = new File(['a'], 'x.csv');
      cmp.dryRun();
      http.expectOne((r) => r.url === '/api/lists/list-1/import')
        .flush(report({ created: 2 }, false));
      expect(cmp.step()).toBe(3);
      expect(cmp.report()!.committed).toBeFalse();
    });

    it('reset clears the file so a stale one cannot be committed later', () => {
      cmp['file'] = new File(['a'], 'x.csv');
      cmp.report.set(report({ created: 1 }));
      cmp.step.set(3);

      cmp.reset();

      expect(cmp.step()).toBe(1);
      expect(cmp.report()).toBeNull();
      expect(cmp['file']).toBeNull();
    });

    it('commit with no file does nothing rather than sending an empty request', () => {
      cmp['file'] = null;
      cmp.busy.set(false);

      cmp.commit();

      // expectNone() alone registers no Jasmine expectation, so a spec relying
      // on it silently cannot fail. Assert observable state as well.
      expect(http.match((r) => r.url === '/api/lists/list-1/import').length).toBe(0);
      expect(cmp.busy()).toBeFalse();
      expect(cmp.step()).toBe(1);
    });
  });

  describe('errors', () => {
    it('surfaces the server detail rather than a generic message', () => {
      cmp['file'] = new File(['a'], 'x.csv');
      cmp.dryRun();
      http.expectOne((r) => r.url === '/api/lists/list-1/import').flush(
        { detail: 'mapping must be a JSON object' },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(cmp.error()).toBe('mapping must be a JSON object');
      expect(cmp.busy()).toBeFalse();
    });
  });
});

/**
 * What the preview promises the commit will do.
 *
 * A twenty-five company list previewed as "Import 0 accounts" while a commit
 * would have created all twenty-five. The button counted `created + merged`,
 * which are **account-grain outcomes**: on a contact-grain file every row
 * reports a contact outcome instead, so the account count was structurally
 * zero. A preview that under-reports is a reason not to press the button.
 */
describe('CsvImportComponent · what the preview promises', () => {
  let fixture: ComponentFixture<CsvImportComponent>;
  let cmp: CsvImportComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CsvImportComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(CsvImportComponent);
    cmp = fixture.componentInstance;
  });

  it('counts the companies a contact file will still create', () => {
    const r = report({ contact_created: 25 }, false, {
      accounts_touched: 25,
      grain: 'contact',
    });

    expect(cmp.willWrite(r)).toBe(25);
    expect(cmp.willWriteContacts(r)).toBe(25);
  });

  it('agrees with the outcome counts on a company file', () => {
    const r = report({ created: 20, merged: 5 });

    expect(cmp.willWrite(r)).toBe(25);
    expect(cmp.willWriteContacts(r)).toBe(0);
  });

  it('does not count skipped rows as people to be written', () => {
    const r = report({ skipped_no_contact: 25 }, false, {
      accounts_touched: 25,
      grain: 'account',
    });

    expect(cmp.willWrite(r)).toBe(25);
    expect(cmp.willWriteContacts(r)).toBe(0);
  });
});
