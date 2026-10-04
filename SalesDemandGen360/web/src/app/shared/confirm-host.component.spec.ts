import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfirmHostComponent } from './confirm-host.component';
import { ConfirmService } from './confirm.service';

/**
 * The in-app confirm box. It replaced `window.confirm`, which the in-app
 * browser suppresses — every delete built on it cancelled itself silently.
 * Escape cancels, Enter confirms; a focused Cancel still means cancel.
 */
describe('ConfirmHostComponent', () => {
  let fixture: ComponentFixture<ConfirmHostComponent>;
  let svc: ConfirmService;

  const press = (key: string) =>
    document.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }));

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ConfirmHostComponent] });
    fixture = TestBed.createComponent(ConfirmHostComponent);
    svc = TestBed.inject(ConfirmService);
    fixture.detectChanges();
  });

  it('names the consequence in the dialog', () => {
    void svc.ask({ title: 'Delete Test1?', body: 'Its 12 accounts stay on their lists.' });
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Delete Test1?');
    expect(text).toContain('12 accounts');
    svc.answer(false);
  });

  it('Enter confirms, even on a destructive question', async () => {
    const answer = svc.ask({ title: 'Delete Test1?', danger: true, confirmLabel: 'Delete' });
    fixture.detectChanges();
    press('Enter');
    expect(await answer).toBeTrue();
  });

  it('Escape cancels', async () => {
    const answer = svc.ask({ title: 'Delete Test1?' });
    fixture.detectChanges();
    press('Escape');
    expect(await answer).toBeFalse();
  });

  it('Enter on a focused Cancel does not confirm', async () => {
    const answer = svc.ask({ title: 'Delete Test1?' });
    fixture.detectChanges();
    const cancel = (fixture.nativeElement as HTMLElement)
      .querySelector('.actions .btn') as HTMLButtonElement;
    cancel.focus();
    press('Enter');
    expect(svc.current()).not.toBeNull();
    cancel.click();
    expect(await answer).toBeFalse();
  });

  it('keys do nothing when no question is open', () => {
    expect(() => press('Enter')).not.toThrow();
    expect(svc.current()).toBeNull();
  });
});
