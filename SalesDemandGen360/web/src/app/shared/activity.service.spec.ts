import { TestBed } from '@angular/core/testing';

import { ActivityBarComponent } from './activity-bar.component';
import { ActivityService } from './activity.service';
import { NotifyService } from './notify.service';
import { SequentialRun } from './sequential-run';
import { of, throwError } from 'rxjs';

/**
 * Messages used to disappear: a success cleared itself in five seconds and a
 * fifth notice pushed the oldest out. Reported as "not able to trace". The
 * Activity log keeps every outcome, with each run's per-account results.
 */
describe('ActivityService', () => {
  beforeEach(() => {
    localStorage.removeItem('sdg360.activity.v1');
    localStorage.removeItem('sdg360.activity.seen');
  });

  it('keeps every outcome, newest first, capped', () => {
    const log = new ActivityService();
    for (let i = 0; i < ActivityService.MAX + 5; i += 1) log.record('success', `m${i}`);
    expect(log.entries().length).toBe(ActivityService.MAX);
    expect(log.entries()[0].text).toBe(`m${ActivityService.MAX + 4}`);
  });

  it('survives a reload', () => {
    new ActivityService().record('error', 'Reveal failed.', 'no credits');
    const reloaded = new ActivityService();
    expect(reloaded.entries()[0].text).toBe('Reveal failed.');
    expect(reloaded.entries()[0].detail).toBe('no credits');
  });

  it('counts errors not yet seen, until the panel is opened', () => {
    const log = new ActivityService();
    log.record('error', 'a');
    log.record('warning', 'b');
    expect(log.unseenErrors()).toBe(1);
    log.toggle();
    expect(log.unseenErrors()).toBe(0);
    expect(log.open()).toBeTrue();
  });

  it('attaches a finished run to the message that reports it, and only that one', () => {
    const log = new ActivityService();
    log.stageRun({ verb: 'Searching', completed: 2, total: 2, cancelled: false, elapsed: '0:05' }, [
      { name: 'Atlassian', kind: 'success', text: '11 new' },
      { name: 'Figma', kind: 'error', text: 'rate limit' },
    ]);
    const summary = log.record('warning', 'Searched 2 accounts');
    const next = log.record('success', 'Saved');
    expect(summary.items.map((i) => i.name)).toEqual(['Atlassian', 'Figma']);
    expect(summary.run?.verb).toBe('Searching');
    expect(next.items).toEqual([]);
  });

  it('says where a message came from', () => {
    const log = new ActivityService();
    log.where.set('List · test');
    expect(log.record('info', 'x').where).toBe('List · test');
    expect(ActivityService.section('/queues/abc')).toBe('Queues');
  });

  it('clears', () => {
    const log = new ActivityService();
    log.record('success', 'x');
    log.clear();
    expect(log.entries()).toEqual([]);
    expect(new ActivityService().entries()).toEqual([]);
  });
});

describe('Every notice lands in the Activity log', () => {
  beforeEach(() => localStorage.removeItem('sdg360.activity.v1'));

  it('records what NotifyService says, and the notice points at it', () => {
    const log = new ActivityService();
    const notify = new NotifyService(log);
    notify.error('Reveal failed.', 'Apollo has no credits left');
    expect(log.entries()[0].kind).toBe('error');
    expect(notify.notices()[0].activityId).toBe(log.entries()[0].id);
  });

  it('keeps each item of a run, with the error for the ones that failed', async () => {
    const log = new ActivityService();
    const run = new SequentialRun(log);
    await run.run<number>({
      verb: 'Enriching',
      items: [{ id: 'a', name: 'Apex' }, { id: 'b', name: 'BlueWave' }],
      call: (id) => (id === 'a' ? of(3) : throwError(() => ({ error: { detail: 'no key' } }))),
      describe: (_, n) => ({ kind: 'success', text: `${n} verified` }),
      onResult: () => undefined,
      onError: () => undefined,
      summary: () => '',
    });
    const entry = log.record('warning', 'Enrichment: 1 verified');
    expect(entry.items).toEqual([
      { name: 'Apex', kind: 'success', text: '3 verified' },
      { name: 'BlueWave', kind: 'error', text: 'no key' },
    ]);
    expect(entry.run?.completed).toBe(2);
  });
});

describe('ActivityBarComponent', () => {
  beforeEach(() => {
    localStorage.removeItem('sdg360.activity.v1');
    localStorage.removeItem('sdg360.activity.seen');
    TestBed.configureTestingModule({ imports: [ActivityBarComponent] });
  });

  function render() {
    const fixture = TestBed.createComponent(ActivityBarComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('shows the latest message and unseen errors while collapsed', () => {
    const log = TestBed.inject(ActivityService);
    log.record('success', 'Imported 12 accounts');
    log.record('error', 'Reveal failed.');
    const el: HTMLElement = render().nativeElement;
    expect(el.querySelector('.latest')!.textContent).toContain('Reveal failed.');
    expect(el.querySelector('.pill.err')!.textContent).toContain('1 error');
    expect(el.querySelector('.list')).toBeNull();
  });

  it('opens to every entry, and filters to errors and warnings', () => {
    const log = TestBed.inject(ActivityService);
    log.record('success', 'ok');
    log.record('warning', 'partial');
    log.record('error', 'failed');
    const fixture = render();
    const el: HTMLElement = fixture.nativeElement;
    (el.querySelector('.head') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelectorAll('.entry').length).toBe(3);
    expect(el.querySelector('.pill.err')).toBeNull();

    fixture.componentInstance.filter.set('problems');
    fixture.detectChanges();
    expect(Array.from(el.querySelectorAll('.entry strong')).map((s) => s.textContent)).toEqual([
      'failed', 'partial',
    ]);
  });
});
