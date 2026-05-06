import {
  AfterViewInit,
  Directive,
  ElementRef,
  EventEmitter,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  Output,
  Renderer2,
  SimpleChanges,
} from '@angular/core';

/**
 * Adds a draggable resize handle to the right edge of a `<th>` cell.
 *
 * Use:
 *   <th mat-header-cell *matHeaderCellDef
 *       resizableColumn
 *       [width]="columnWidths['companyName']"
 *       (resized)="onColumnResized('companyName', $event)">Company</th>
 *
 * Requires the parent `<table>` to have CSS `table-layout: fixed`, otherwise
 * Material's auto-layout ignores the inline width.
 */
@Directive({
  selector: '[resizableColumn]',
  standalone: true,
})
export class ResizableColumnDirective implements AfterViewInit, OnChanges, OnDestroy {
  @Input() width?: number;
  @Input() minWidth = 60;

  @Output() resized = new EventEmitter<number>();

  private handle?: HTMLElement;
  private startX = 0;
  private startWidth = 0;
  private dragging = false;

  // Bound listeners stored so removeEventListener can find them.
  private mouseMoveListener?: (e: MouseEvent) => void;
  private mouseUpListener?: () => void;
  private touchMoveListener?: (e: TouchEvent) => void;
  private touchEndListener?: () => void;

  constructor(
    private el: ElementRef<HTMLElement>,
    private renderer: Renderer2,
    private zone: NgZone,
  ) {}

  ngAfterViewInit(): void {
    const th = this.el.nativeElement;
    const computed = getComputedStyle(th).position;
    if (computed === 'static' || !computed) {
      this.renderer.setStyle(th, 'position', 'relative');
    }

    const handle = this.renderer.createElement('span') as HTMLElement;
    this.renderer.addClass(handle, 'resize-handle');
    // Inline fallback styles so the handle works even if global SCSS is missing.
    this.renderer.setStyle(handle, 'position', 'absolute');
    this.renderer.setStyle(handle, 'top', '0');
    this.renderer.setStyle(handle, 'right', '0');
    this.renderer.setStyle(handle, 'width', '5px');
    this.renderer.setStyle(handle, 'height', '100%');
    this.renderer.setStyle(handle, 'cursor', 'col-resize');
    this.renderer.setStyle(handle, 'user-select', 'none');
    this.renderer.setStyle(handle, 'z-index', '1');
    this.renderer.appendChild(th, handle);
    this.handle = handle;

    this.zone.runOutsideAngular(() => {
      handle.addEventListener('mousedown', this.onMouseDown);
      handle.addEventListener('touchstart', this.onTouchStart, { passive: false });
    });

    this.applyWidth();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['width']) {
      this.applyWidth();
    }
  }

  ngOnDestroy(): void {
    if (this.handle) {
      this.handle.removeEventListener('mousedown', this.onMouseDown);
      this.handle.removeEventListener('touchstart', this.onTouchStart);
    }
    this.cleanupDrag();
  }

  private applyWidth(): void {
    if (this.width && this.width >= this.minWidth) {
      this.renderer.setStyle(this.el.nativeElement, 'width', `${this.width}px`);
    }
  }

  private onMouseDown = (e: MouseEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    this.startDrag(e.clientX);

    this.mouseMoveListener = (ev: MouseEvent) => this.handleMove(ev.clientX);
    this.mouseUpListener = () => this.endDrag();
    document.addEventListener('mousemove', this.mouseMoveListener);
    document.addEventListener('mouseup', this.mouseUpListener);
  };

  private onTouchStart = (e: TouchEvent): void => {
    if (!e.touches.length) return;
    e.preventDefault();
    e.stopPropagation();
    this.startDrag(e.touches[0].clientX);

    this.touchMoveListener = (ev: TouchEvent) => {
      if (ev.touches.length) this.handleMove(ev.touches[0].clientX);
    };
    this.touchEndListener = () => this.endDrag();
    document.addEventListener('touchmove', this.touchMoveListener, { passive: false });
    document.addEventListener('touchend', this.touchEndListener);
  };

  private startDrag(clientX: number): void {
    this.dragging = true;
    this.startX = clientX;
    this.startWidth = this.el.nativeElement.getBoundingClientRect().width;
    if (this.handle) this.renderer.addClass(this.handle, 'resizing');
    this.renderer.addClass(document.body, 'col-resizing');
  }

  private handleMove(clientX: number): void {
    if (!this.dragging) return;
    const delta = clientX - this.startX;
    const next = Math.max(this.minWidth, Math.round(this.startWidth + delta));
    this.renderer.setStyle(this.el.nativeElement, 'width', `${next}px`);
  }

  private endDrag(): void {
    if (!this.dragging) return;
    this.dragging = false;
    if (this.handle) this.renderer.removeClass(this.handle, 'resizing');
    this.renderer.removeClass(document.body, 'col-resizing');
    this.cleanupDrag();
    const final = Math.round(this.el.nativeElement.getBoundingClientRect().width);
    this.zone.run(() => this.resized.emit(final));
  }

  private cleanupDrag(): void {
    if (this.mouseMoveListener) {
      document.removeEventListener('mousemove', this.mouseMoveListener);
      this.mouseMoveListener = undefined;
    }
    if (this.mouseUpListener) {
      document.removeEventListener('mouseup', this.mouseUpListener);
      this.mouseUpListener = undefined;
    }
    if (this.touchMoveListener) {
      document.removeEventListener('touchmove', this.touchMoveListener);
      this.touchMoveListener = undefined;
    }
    if (this.touchEndListener) {
      document.removeEventListener('touchend', this.touchEndListener);
      this.touchEndListener = undefined;
    }
  }
}
