import { Component, Input } from '@angular/core';

/**
 * Inline SVG icons.
 *
 * Inline rather than a sprite sheet or an icon font: the set is small, they
 * inherit `currentColor` so they follow the button's text through both themes,
 * and there is no extra request to fail on a cold load.
 *
 * Drawn with literal template branches rather than `[innerHTML]`. Angular's
 * sanitiser strips SVG child elements from bound HTML, so that route needs a
 * `bypassSecurityTrustHtml` — a real XSS escape hatch opened for the sake of
 * drawing a plus sign. Literal markup needs no bypass at all.
 */
export type IconName =
  | 'plus'
  | 'upload'
  | 'refresh'
  | 'check'
  | 'x'
  | 'eye'
  | 'trash'
  | 'back'
  | 'pause'
  | 'play'
  | 'edit'
  | 'lock'
  | 'undo'
  | 'info';

@Component({
  selector: 'app-icon',
  standalone: true,
  template: `
    <svg
      [attr.width]="size"
      [attr.height]="size"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @switch (name) {
        @case ('plus') {
          <path d="M12 5v14M5 12h14" />
        }
        @case ('upload') {
          <path d="M12 16V4M7 9l5-5 5 5" />
          <path d="M4 17v2a1.8 1.8 0 0 0 1.8 1.8h12.4A1.8 1.8 0 0 0 20 19v-2" />
        }
        @case ('refresh') {
          <path d="M3 12a9 9 0 0 1 15.3-6.4L21 8M21 3v5h-5" />
          <path d="M21 12a9 9 0 0 1-15.3 6.4L3 16m0 5v-5h5" />
        }
        @case ('check') {
          <path d="m4 12 5 5L20 6" />
        }
        @case ('x') {
          <path d="M6 6l12 12M18 6 6 18" />
        }
        @case ('lock') {
          <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
          <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
        }
        @case ('undo') {
          <path d="M3.5 8.5h9a6 6 0 0 1 0 12H8" />
          <path d="M3.5 8.5 8 4m-4.5 4.5L8 13" />
        }
        @case ('eye') {
          <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
          <circle cx="12" cy="12" r="3.1" />
        }
        @case ('trash') {
          <path d="M4.5 6.5h15" />
          <path d="M9.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v1.5" />
          <path d="M6.5 6.5 7.4 19a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5l.9-12.5" />
        }
        @case ('back') {
          <path d="M15 5 8 12l7 7" />
        }
        @case ('pause') {
          <path d="M9.5 5v14M14.5 5v14" />
        }
        @case ('play') {
          <path d="M7 4.5v15l12-7.5Z" />
        }
        @case ('edit') {
          <path d="M4 20h4L18.5 9.5a2 2 0 0 0-4-4L4 16v4Z" />
        }
        @case ('info') {
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11.2v5" />
          <path d="M12 7.6h.01" />
        }
      }
    </svg>
  `,
  styles: [':host { display: inline-flex; align-items: center; }'],
})
export class IconComponent {
  /** Decorative: the button's own text is the accessible name, so the icon is
   *  aria-hidden rather than repeating it to a screen reader. */
  @Input({ required: true }) name!: IconName;
  @Input() size = 14;
}
