import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { SequentialRun } from './sequential-run';

/**
 * "Researching 3 of 8… 0:42", a bar, what has come back so far, and Cancel.
 *
 * Renders nothing while its run is idle, so a screen can place it once and
 * forget it. The outcome, when the run ends, is a corner notice — this only
 * covers the part in between, which used to be a spinner that never moved.
 */
@Component({
  selector: 'app-run-progress',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="prog" *ngIf="run.state() as s" role="status" aria-live="polite">
      <div class="line">
        <span class="spin" aria-hidden="true"></span>
        <strong>{{ s.verb }} {{ position(s.done, s.total) }} of {{ s.total }}…</strong>
        <span class="row-sub mono">{{ run.elapsed() }}</span>
        <span class="row-sub cur" *ngIf="s.current" [title]="s.current">{{ s.current }}</span>
        <span class="spacer"></span>
        <button type="button" class="btn" (click)="run.cancel()" [disabled]="s.cancelling">
          {{ s.cancelling ? 'Stopping after this one…' : 'Cancel' }}
        </button>
      </div>
      <div class="bar" aria-hidden="true">
        <div class="fill" [style.width.%]="s.total ? (s.done / s.total) * 100 : 0"></div>
      </div>
      <p class="row-sub so-far" *ngIf="s.summary">So far: {{ s.summary }}</p>
    </div>
  `,
  styles: [
    `
      .prog { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
              margin: 8px 0 12px; background: var(--card, #fff); }
      .line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
      .line strong { font-size: .86rem; }
      .cur { max-width: 34ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .spacer { flex: 1; }
      .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--line);
              border-top-color: var(--accent); animation: rp-spin .8s linear infinite; }
      @keyframes rp-spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
      .bar { height: 5px; border-radius: 3px; background: var(--line); margin-top: 8px;
             overflow: hidden; }
      .fill { height: 100%; background: var(--accent); transition: width .3s ease; }
      .so-far { margin: 6px 0 0; }
    `,
  ],
})
export class RunProgressComponent {
  @Input({ required: true }) run!: SequentialRun;

  /** The item being worked on, counting from one. */
  position(done: number, total: number): number {
    return Math.min(done + 1, total);
  }
}
