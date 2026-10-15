import { CommonModule } from '@angular/common';
import { Component, Input, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ResearchTier } from '../core/lists.service';
import { ResearchModeService, TIERS } from './research-mode.service';

/**
 * What depth research runs at here, on the line that already says what you
 * are looking at.
 *
 * **On the status line rather than in the run dialog alone**, because the
 * depth is a property of what you are doing, not of the moment you press a
 * button: a rep working one account deliberately should be able to see that
 * every run on this screen will be deep without opening a dialog to find out.
 *
 * **The switch lasts for the visit.** Navigating away resets it, so going
 * deep to work one account cannot silently become the setting that
 * researches the next two hundred. Where it came from is named, so a rep can
 * tell "deep because I said so" from "deep because this list is".
 */
@Component({
  selector: 'app-research-mode',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <span class="mode" [class.on]="svc.overridden()">
      <span class="k">research</span>
      <select [ngModel]="svc.effective(scopeDefault)"
              (ngModelChange)="svc.pick($event)"
              [title]="why()"
              aria-label="Research depth for this screen">
        <option *ngFor="let t of tiers" [value]="t.value">{{ t.label }}</option>
      </select>
      <!-- Only when it differs from what this screen would otherwise do.
           A permanent "default" badge is noise on every page. -->
      <button type="button" class="undo" *ngIf="svc.overridden()"
              (click)="svc.pick(null)" title="Back to the default for this screen">
        reset
      </button>
    </span>
  `,
  styles: [
    `
      .mode { display: inline-flex; align-items: center; gap: 6px;
              font-size: 0.74rem; color: var(--muted); }
      .k { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;
           letter-spacing: 0.07em; text-transform: uppercase; color: var(--faint); }
      select { font: inherit; color: inherit; background: none; cursor: pointer;
               border: 1px solid var(--line); border-radius: 6px; padding: 2px 4px; }
      .mode.on select { border-color: var(--accent, #3b5bdb); color: var(--text); }
      .undo { font: inherit; color: var(--muted); background: none; cursor: pointer;
              border: 0; padding: 2px 3px; text-decoration: underline; }
    `,
  ],
})
export class ResearchModeComponent {
  svc = inject(ResearchModeService);
  readonly tiers = TIERS;

  /**
   * What this screen would use with nothing picked — a list's own setting,
   * usually. Null or absent means the installation's default applies.
   */
  @Input() scopeDefault: ResearchTier | null = null;
  /** What `scopeDefault` is, for the tooltip: "this list", "its list". */
  @Input() scopeName = 'this list';

  why(): string {
    const tier = this.svc.effective(this.scopeDefault);
    const detail = TIERS.find((t) => t.value === tier)?.detail ?? '';
    if (this.svc.overridden()) {
      return `${detail}\n\nPicked for this visit. Leaving the screen puts it back.`;
    }
    const from = this.scopeDefault
      ? `set on ${this.scopeName}`
      : `the installation's default — ${this.scopeName} does not override it`;
    return `${detail}\n\n${from}.`;
  }
}
