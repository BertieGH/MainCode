import { NotifyService } from './notify.service';

/**
 * Outcome messages in one place. Success clears itself; a partial result or
 * an error stays until dismissed; Retry is offered only where it is safe.
 */
describe('NotifyService', () => {
  it('offers Retry when asked, and runs it', () => {
    const svc = new NotifyService();
    let tried = 0;
    svc.error('Could not save.', 'timeout', { retry: () => (tried += 1) });
    const notice = svc.notices()[0];
    expect(notice.action?.label).toBe('Retry');
    notice.action!.run();
    expect(tried).toBe(1);
  });

  it('offers no action unless one is given', () => {
    const svc = new NotifyService();
    svc.warning('9 added · 1 refused', 'not confirmed');
    expect(svc.notices()[0].action).toBeNull();
    expect(svc.notices()[0].detail).toBe('not confirmed');
  });

  it('treats no answer or a server fault as worth retrying, and a refusal as not', () => {
    expect(NotifyService.retryable({ status: 0 })).toBeTrue();
    expect(NotifyService.retryable({ status: 503 })).toBeTrue();
    expect(NotifyService.retryable({ status: 409 })).toBeFalse();
    expect(NotifyService.retryable({ status: 422 })).toBeFalse();
  });

  it('keeps the stack short', () => {
    const svc = new NotifyService();
    for (let i = 0; i < 6; i += 1) svc.error(`e${i}`);
    expect(svc.notices().map((n) => n.text)).toEqual(['e2', 'e3', 'e4', 'e5']);
  });
});
