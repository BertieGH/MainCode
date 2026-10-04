import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { Router, provideRouter } from '@angular/router';

import { ListsComponent } from './lists.component';
import { AccountList } from '../core/lists.service';
import { ConfirmService } from '../shared/confirm.service';
import { NotifyService } from '../shared/notify.service';

/**
 * Two things this screen has to get right:
 *
 *  - a newly created list is empty, and the CSV uploader lives on the detail
 *    page, so creating one must lead somewhere rather than leaving a row with
 *    nothing in it and no visible way to fill it;
 *  - delete is offered on every row, because the recoverable mistake is a
 *    mis-mapped import and hiding the action made it look permanent. What may
 *    actually go is the server's decision: it refuses a list whose accounts
 *    have been researched or promoted, and says which.
 */

function list(over: Partial<AccountList> = {}): AccountList {
  return {
    id: 'list-1',
    label: 'Q3 DevOps ISVs - US',
    description: null,
    source: 'csv',
    created_by: 'bertie',
    account_count: 6,
    // Untargeted and unenriched by default — the state a list is actually in
    // the moment it is created, so a test that cares has to say so.
    service_codes: [],
    icp_names: [],
    contact_count: 0,
    verified_count: 0,
    created_at: '2026-03-14T09:00:00Z',
    ...over,
  };
}

describe('ListsComponent', () => {
  let fixture: ComponentFixture<ListsComponent>;
  let cmp: ListsComponent;
  let http: HttpTestingController;
  let router: Router;

  function boot(rows: AccountList[]): void {
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/lists').flush(rows);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ListsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ListsComponent);
    cmp = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
  });

  afterEach(() => http.verify());

  describe('creating a list leads to the uploader', () => {
    beforeEach(() => boot([]));

    it('opens the new list with the importer ready', () => {
      cmp.draft.label = 'Verify import flow';
      cmp.create();

      http
        .expectOne((r) => r.method === 'POST' && r.url === '/api/lists')
        .flush(list({ id: 'new-1', account_count: 0 }));

      expect(router.navigate).toHaveBeenCalledWith(['/lists', 'new-1'], {
        queryParams: { import: 1 },
      });
    });

    it('stays put when the empty variant is used', () => {
      cmp.draft.label = 'Fill in later';
      cmp.create(false);

      http
        .expectOne((r) => r.method === 'POST' && r.url === '/api/lists')
        .flush(list({ id: 'new-2', account_count: 0 }));

      expect(router.navigate).not.toHaveBeenCalled();
      http.expectOne((r) => r.url === '/api/lists').flush([]); // the reload
    });

    it('keeps the form open and says so when creation fails', () => {
      cmp.creating.set(true);
      cmp.draft.label = 'Doomed';
      cmp.create();
      expect(cmp.creatingBusy()).toBe('import', 'the button shows it is working');
      http
        .expectOne((r) => r.method === 'POST' && r.url === '/api/lists')
        .flush({}, { status: 500, statusText: 'Error' });

      // In the corner, not a box pinned above the table that scrolls away.
      const notices = TestBed.inject(NotifyService).notices();
      expect(notices.map((n) => `${n.kind}: ${n.text}`)).toContain('error: Could not create the list.');
      expect(cmp.creatingBusy()).toBeNull();
      expect(cmp.creating()).toBeTrue();
      expect(cmp.draft.label).toBe('Doomed', 'what was typed is kept');
      expect(router.navigate).not.toHaveBeenCalled();
    });
  });

  describe('showing how far a list has got', () => {
    /**A list index that only shows a label makes you open every row to find
    out which are ready and which have not been started.*/

    const text = () => fixture.nativeElement.textContent as string;

    it('shows when a list was created, not who by, under "Created"', () => {
      // The column sorts on created_at; it used to render created_by, so the
      // heading described one field and the cell showed another.
      boot([list({ created_at: '2026-03-14T09:00:00Z', created_by: 'bertie' })]);
      expect(text()).toContain('Mar 14, 2026');
      // The person is still there, just no longer masquerading as the date.
      expect(text()).toContain('bertie');
    });

    it('shows what a list is worked for', () => {
      boot([list({ service_codes: ['EIA'], icp_names: ['Mid-market SaaS'] })]);
      expect(text()).toContain('EIA');
      expect(text()).toContain('Mid-market SaaS');
    });

    it('says plainly when a list has no targeting', () => {
      // Not blank: a list nobody has targeted cannot be enriched deliberately,
      // and an empty cell reads as "nothing to see" rather than "unfinished".
      boot([list()]);
      expect(text()).toContain('not set');
    });

    it('shows enrichment as two numbers, not a percentage', () => {
      // "0 of 40" and "0 of 0" are different situations; a percentage renders
      // both as nothing.
      boot([list({ contact_count: 40, verified_count: 12 })]);
      expect(text()).toContain('12/40');
    });

    it('shows a dash when there are no contacts at all', () => {
      boot([list({ contact_count: 0, verified_count: 0 })]);
      expect(text()).toContain('—');
    });

    it('says none verified when there are contacts but no addresses', () => {
      // The state that matters: the list is populated and enrichment has not
      // run, which is different from having nobody to enrich.
      boot([list({ contact_count: 9, verified_count: 0 })]);
      expect(text()).toContain('none verified');
    });
  });

  describe('deleting only what holds nothing', () => {
    let ask: jasmine.Spy;
    let notices: () => string[];

    beforeEach(() => {
      ask = spyOn(TestBed.inject(ConfirmService), 'ask');
      const notify = TestBed.inject(NotifyService);
      notices = () => notify.notices().map((n) => `${n.kind}: ${n.text} ${n.detail ?? ''}`);
    });

    function actionLabels(): string[] {
      return fixture.debugElement
        .queryAll(By.css('td.actcol a, td.actcol button'))
        .map((b) => b.nativeElement.getAttribute('aria-label') as string);
    }

    function deleteRow(label = 'Empty'): Promise<void> {
      const del = cmp.actions.find((a) => a.key === 'delete')!;
      const row = cmp.lists().find((l) => l.label === label)!;
      return cmp.onBulk({ action: del, rows: [row], skipped: [] });
    }

    it('offers delete on every row, not only the empty ones', () => {
      // Hiding it unless the list was empty made the one genuinely
      // recoverable mistake — a mis-mapped import — look permanent. The
      // server refuses what is actually depended on, and says why.
      boot([
        list({ id: 'a', label: 'Full', account_count: 6 }),
        list({ id: 'b', label: 'Empty', account_count: 0 }),
      ]);
      expect(actionLabels()).toEqual([
        'Open Full',
        'More actions for Full',
        'Open Empty',
        'More actions for Empty',
      ]);
      expect(cmp.actions.find((a) => a.key === 'delete')!.can)
        .withContext('no client-side condition: the server is the authority')
        .toBeUndefined();
    });

    it('names the number of accounts before it is confirmed', async () => {
      // "Delete for good?" reads the same over fourteen accounts as over
      // none, and only one of those deserves a pause.
      boot([list({ id: 'a', label: 'Full', account_count: 6 })]);
      ask.and.resolveTo(false);
      const asked = deleteRow('Full');
      // What deleting would do is asked of the server first, and said.
      http.expectOne('/api/lists/a/delete-preview').flush({
        accounts: 6, on_other_lists: 1, in_queues: 2, dormant: 2, deleted: 1,
      });
      await asked;
      const q = ask.calls.mostRecent().args[0];
      expect(q.title).toContain('Full');
      expect(q.body).toContain('6 accounts');
      expect(q.body).toContain('2 stay live through a campaign queue');
      expect(q.body).toContain('2 go dormant');
      expect(q.danger).toBeTrue();
    });

    it('points the import shortcut at the uploader, not just the list', async () => {
      boot([list({ id: 'a', label: 'Full' })]);
      const imp = cmp.actions.find((a) => a.key === 'import')!;
      expect(imp.bulk).withContext('importing is into one list at a time').toBeFalse();
      await cmp.onBulk({ action: imp, rows: [cmp.lists()[0]], skipped: [] });
      expect(router.navigate).toHaveBeenCalledWith(['/lists', 'a'], {
        queryParams: { import: 1 },
      });
    });

    it('asks in the app, not with window.confirm', async () => {
      // The in-app browser suppresses native dialogs: window.confirm returned
      // false in 45 ms without drawing anything, so every delete cancelled
      // itself silently.
      boot([list({ id: 'b', label: 'Empty', account_count: 0 })]);
      const native = spyOn(window, 'confirm');
      ask.and.resolveTo(false);
      await deleteRow();
      expect(ask).toHaveBeenCalled();
      expect(native).not.toHaveBeenCalled();
    });

    it('sends only once confirmed, and says what went', async () => {
      boot([list({ id: 'b', label: 'Empty', account_count: 0 })]);
      ask.and.resolveTo(true);
      await deleteRow();
      const req = http.expectOne('/api/lists/b');
      expect(req.request.method).toBe('DELETE');
      req.flush({ accounts_deleted: 0, accounts_kept: 0 });
      expect(cmp.lists().length).toBe(0);
      expect(notices().join('\n')).toContain('success: Deleted Empty');
    });

    it('keeps the row when the server refuses, and gives its reason', async () => {
      // An import can land between the page rendering and the click, so the
      // cached count is not the authority.
      boot([list({ id: 'b', label: 'Empty', account_count: 0 })]);
      ask.and.resolveTo(true);
      await deleteRow();
      http.expectOne('/api/lists/b').flush(
        { detail: "'Empty' holds 3 account(s) and cannot be deleted" },
        { status: 409, statusText: 'Conflict' },
      );
      expect(cmp.lists().length).toBe(1);
      expect(notices().join('\n')).toContain('cannot be deleted');
      expect(notices().join('\n')).toContain('error:');
    });

    it('backing out sends nothing', async () => {
      boot([list({ id: 'b', label: 'Empty', account_count: 0 })]);
      ask.and.resolveTo(false);
      await deleteRow();
      expect(http.match(() => true).length)
        .withContext('declining the confirmation must not delete anything')
        .toBe(0);
      expect(cmp.lists().length).toBe(1);
    });
  });
});
