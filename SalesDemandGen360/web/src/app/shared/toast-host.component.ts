import { CommonModule } from '@angular/common';

import { ActivityService } from './activity.service';
import { Component, inject } from '@angular/core';

import { Notice, NotifyService } from './notify.service';

/** The notice stack behind `NotifyService`. Mounted once, in the app shell. */
@Component({
  selector: 'app-toast-host',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="stack">
      <div *ngFor="let n of svc.notices(); trackBy: byId" class="toast" [ngClass]="n.kind"
           [attr.role]="n.kind === 'error' || n.kind === 'warning' ? 'alert' : 'status'">
        <span class="mark" aria-hidden="true"></span>
        <div class="body">
          <div class="text">{{ n.text }}</div>
          <div class="detail" *ngIf="n.detail">{{ n.detail }}</div>
          <button type="button" class="act" *ngIf="n.action"
                  (click)="svc.dismiss(n.id); n.action.run()">{{ n.action.label }}</button>
          <button type="button" class="act" *ngIf="n.activityId"
                  (click)="svc.dismiss(n.id); activity.reveal(n.activityId)">View in activity</button>
        </div>
        <button type="button" class="x" (click)="svc.dismiss(n.id)" aria-label="Dismiss">×</button>
      </div>
    </div>
  `,
  styles: [
    `
      .stack { position: fixed; right: 18px; bottom: 18px; z-index: 900; display: flex;
               flex-direction: column; gap: 8px; width: min(380px, calc(100vw - 36px)); }
      .toast { display: flex; gap: 10px; align-items: flex-start; background: var(--card, #fff);
               border: 1px solid var(--line); border-left-width: 4px; border-radius: 8px;
               padding: 10px 10px 10px 12px; box-shadow: 0 8px 26px rgba(0, 0, 0, 0.16);
               font-size: 0.84rem; }
      .toast.success { border-left-color: var(--good, #2f7a54); }
      .toast.info { border-left-color: var(--accent, #1f6f64); }
      .toast.warning { border-left-color: var(--warn, #b8801f); }
      .toast.error { border-left-color: var(--critical, #b34a3f); }
      .mark { width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; flex: none;
              background: currentColor; opacity: 0.5; }
      .success .mark { background: var(--good, #2f7a54); opacity: 1; }
      .info .mark { background: var(--accent, #1f6f64); opacity: 1; }
      .warning .mark { background: var(--warn, #b8801f); opacity: 1; }
      .error .mark { background: var(--critical, #b34a3f); opacity: 1; }
      .body { flex: 1; min-width: 0; }
      .text { font-weight: 500; }
      .detail { color: var(--muted); font-size: 0.78rem; margin-top: 2px; overflow-wrap: anywhere; }
      .x { border: none; background: none; cursor: pointer; font-size: 1.1rem; line-height: 1;
           color: var(--muted); padding: 0 2px; }
      .x:hover { color: inherit; }
      .act { margin-top: 6px; border: 1px solid var(--line); background: none; cursor: pointer;
             border-radius: 5px; padding: 2px 9px; font: inherit; font-size: .76rem;
             color: var(--accent); }
      .act:hover { background: var(--line); }
    `,
  ],
})
export class ToastHostComponent {
  svc = inject(NotifyService);
  activity = inject(ActivityService);
  byId = (_: number, n: Notice) => n.id;
}
