import { Subject, of, throwError } from 'rxjs';

import { SequentialRun } from './sequential-run';

/**
 * The loop behind "Researching 3 of 8… 0:42".
 *
 * Resolve, enrich and research used to be one request for the whole
 * selection: a spinner that never moved, then everything at once or nothing.
 * One item at a time is what lets the screen report real progress, show
 * partial results, and stop between items.
 */
describe('SequentialRun', () => {
  const items = [
    { id: 'a', name: 'Apex' },
    { id: 'b', name: 'BlueWave' },
    { id: 'c', name: 'Cobalt' },
  ];
  const quiet = { onResult: () => undefined, onError: () => undefined, summary: () => '' };

  it('works through the items one at a time, in order', async () => {
    const run = new SequentialRun();
    const asked: string[] = [];
    const out = await run.run<number>({
      ...quiet, verb: 'Researching', items,
      call: (id) => { asked.push(id); return of(1); },
    });
    expect(asked).toEqual(['a', 'b', 'c']);
    expect(out).toEqual({ completed: 3, cancelled: false, stopped: false });
    expect(run.state()).toBeNull();
  });

  it('reports where it is while it runs', async () => {
    const run = new SequentialRun();
    const seen: string[] = [];
    let n = 0;
    await run.run<number>({
      verb: 'Enriching', items,
      call: (id) => {
        const s = run.state()!;
        seen.push(`${s.verb} ${s.done + 1} of ${s.total} (${s.current})`);
        return of(1);
      },
      onResult: () => { n += 1; return undefined; },
      onError: () => undefined,
      summary: () => `${n} done`,
    });
    expect(seen).toEqual([
      'Enriching 1 of 3 (Apex)', 'Enriching 2 of 3 (BlueWave)', 'Enriching 3 of 3 (Cobalt)',
    ]);
  });

  it('one failure costs one item, not the run', async () => {
    const run = new SequentialRun();
    const failed: string[] = [];
    const out = await run.run<number>({
      ...quiet, verb: 'Researching', items,
      call: (id) => (id === 'b' ? throwError(() => new Error('down')) : of(1)),
      onError: (item) => { failed.push(item.name); return undefined; },
    });
    expect(failed).toEqual(['BlueWave']);
    expect(out.completed).toBe(3);
  });

  it('stops when a result says the same refusal would repeat', async () => {
    const run = new SequentialRun();
    const asked: string[] = [];
    const out = await run.run<number>({
      ...quiet, verb: 'Researching', items,
      call: (id) => { asked.push(id); return of(1); },
      onResult: () => 'stop',
    });
    expect(asked).toEqual(['a']);
    expect(out).toEqual({ completed: 1, cancelled: false, stopped: true });
  });

  it('cancel waits for the item in flight, then stops before the next', async () => {
    const run = new SequentialRun();
    const gate = new Subject<number>();
    const asked: string[] = [];
    const done = run.run<number>({
      ...quiet, verb: 'Researching', items,
      call: (id) => { asked.push(id); return id === 'a' ? gate : of(1); },
    });
    await Promise.resolve();
    expect(run.state()!.current).toBe('Apex');

    run.cancel();
    expect(run.state()!.cancelling).toBeTrue();
    gate.next(1);
    gate.complete();

    const out = await done;
    expect(asked).toEqual(['a'], 'started another item after Cancel');
    expect(out).toEqual({ completed: 1, cancelled: true, stopped: false });
    expect(run.state()).toBeNull();
  });
});
