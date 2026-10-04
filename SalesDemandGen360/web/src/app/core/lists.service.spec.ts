import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { ListsService, asUnsortableField } from './lists.service';
import { NO_SORT } from '../shared/sortable';

describe('ListsService', () => {
  let api: ListsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [ListsService, provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ListsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('sort parameters', () => {
    it('sends no sort params when unsorted', () => {
      api.lists(NO_SORT).subscribe();
      const req = http.expectOne((r) => r.url === '/api/lists');
      expect(req.request.params.has('sort')).toBeFalse();
      expect(req.request.params.has('dir')).toBeFalse();
      req.flush([]);
    });

    it('sends both params when sorted', () => {
      api.lists({ field: 'label', direction: 'desc' }).subscribe();
      const req = http.expectOne((r) => r.url === '/api/lists');
      expect(req.request.params.get('sort')).toBe('label');
      expect(req.request.params.get('dir')).toBe('desc');
      req.flush([]);
    });
  });

  describe('CSV import', () => {
    const file = new File(['a,b\n1,2'], 'x.csv', { type: 'text/csv' });

    it('defaults to a dry run', () => {
      // The server also defaults to dry_run=true. Two defaults rather than one,
      // because an import that writes because a flag was forgotten is the
      // failure worth being redundant about.
      api.importCsv('list-1', file, { name: 'a' }).subscribe();
      const req = http.expectOne((r) => r.url === '/api/lists/list-1/import');
      expect(req.request.params.get('dry_run')).toBe('true');
      req.flush({ total_rows: 0, committed: false, counts: {}, rows: [] });
    });

    it('only commits when explicitly told to', () => {
      api.importCsv('list-1', file, { name: 'a' }, false).subscribe();
      const req = http.expectOne((r) => r.url === '/api/lists/list-1/import');
      expect(req.request.params.get('dry_run')).toBe('false');
      req.flush({ total_rows: 0, committed: true, counts: {}, rows: [] });
    });

    it('sends the mapping as JSON and the file as multipart', () => {
      api.importCsv('list-1', file, { name: 'Company', domain: null }).subscribe();
      const req = http.expectOne((r) => r.url === '/api/lists/list-1/import');
      expect(JSON.parse(req.request.params.get('mapping')!)).toEqual({
        name: 'Company',
        domain: null,
      });
      expect(req.request.body instanceof FormData).toBeTrue();
      req.flush({ total_rows: 0, committed: false, counts: {}, rows: [] });
    });
  });

  describe('search', () => {
    it('omits q when no term is given', () => {
      api.accounts(NO_SORT).subscribe();
      const req = http.expectOne((r) => r.url === '/api/accounts');
      expect(req.request.params.has('q')).toBeFalse();
      req.flush([]);
    });

    it('passes the term as a bound parameter, not interpolated', () => {
      api.accounts(NO_SORT, "o'brien & co").subscribe();
      const req = http.expectOne((r) => r.url === '/api/accounts');
      expect(req.request.params.get('q')).toBe("o'brien & co");
      req.flush([]);
    });
  });
});

describe('asUnsortableField', () => {
  it('recognises the allowlist rejection', () => {
    const err = {
      error: { detail: { error: 'unsortable_field', field: 'bogus', allowed: ['name'] } },
    };
    expect(asUnsortableField(err)?.field).toBe('bogus');
  });

  it('returns null for any other error', () => {
    expect(asUnsortableField({ error: { detail: 'not found' } })).toBeNull();
    expect(asUnsortableField(null)).toBeNull();
    expect(asUnsortableField({})).toBeNull();
  });
});
