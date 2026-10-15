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

  describe('a question with a choice in it', () => {
    const TIERS = [
      { value: 'light', label: 'Light', cost: '~$0.84' },
      { value: 'standard', label: 'Standard', cost: '~$1.26' },
      { value: 'deep', label: 'Deep', cost: '~$2.94' },
    ];

    function radios(): HTMLInputElement[] {
      return Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll('.choice input'),
      ) as HTMLInputElement[];
    }

    function ok(): HTMLButtonElement {
      const buttons = (fixture.nativeElement as HTMLElement)
        .querySelectorAll('.actions .btn');
      return buttons[buttons.length - 1] as HTMLButtonElement;
    }

    it('answers with the chosen value, not a bare yes', async () => {
      const answer = svc.ask({ title: 'Research 12?', choices: TIERS, chosen: 'standard' });
      fixture.detectChanges();
      radios()[0].dispatchEvent(new Event('change'));
      fixture.detectChanges();
      ok().click();
      expect(await answer).toBe('light');
    });

    it('starts on the choice the caller asked for', async () => {
      const answer = svc.ask({ title: 'Research 12?', choices: TIERS, chosen: 'deep' });
      fixture.detectChanges();
      ok().click();
      expect(await answer).toBe('deep');
    });

    it('falls back to the first choice when none is named', async () => {
      const answer = svc.ask({ title: 'Research 12?', choices: TIERS });
      fixture.detectChanges();
      ok().click();
      expect(await answer).toBe('light');
    });

    it('Enter carries the choice too', async () => {
      // Without this, Enter answers a dialog showing three prices as a bare
      // `true` and the caller buys whichever tier it defaulted to.
      const answer = svc.ask({ title: 'Research 12?', choices: TIERS, chosen: 'deep' });
      fixture.detectChanges();
      press('Enter');
      expect(await answer).toBe('deep');
    });

    it('cancel is still false, not a choice', async () => {
      const answer = svc.ask({ title: 'Research 12?', choices: TIERS });
      fixture.detectChanges();
      press('Escape');
      expect(await answer).toBeFalse();
    });

    it('does not leave the previous answer selected', async () => {
      // One dialog is reused for every question. Without the reset, a second
      // run opens already answering the first one.
      const first = svc.ask({ title: 'A?', choices: TIERS, chosen: 'deep' });
      fixture.detectChanges();
      ok().click();
      expect(await first).toBe('deep');

      const second = svc.ask({ title: 'B?', choices: TIERS });
      fixture.detectChanges();
      ok().click();
      expect(await second).toBe('light');
    });

    it('a question with no choices still answers true', async () => {
      const answer = svc.ask({ title: 'Delete Test1?' });
      fixture.detectChanges();
      ok().click();
      expect(await answer).toBeTrue();
    });
  });
});
