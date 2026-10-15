import { Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ResearchModeService } from './research-mode.service';

/**
 * Three places can answer "how deep does research go here", and the nearest
 * wins. The two things that make that safe rather than confusing are below:
 * the server resolves the far two into one number so no screen has to know
 * the order, and a pick lasts for the visit and no longer.
 */
describe('ResearchModeService', () => {
  let svc: ResearchModeService;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([{ path: '**', children: [] }])],
    });
    svc = TestBed.inject(ResearchModeService);
    router = TestBed.inject(Router);
  });

  it('falls back to the built-in default before anything is loaded', () => {
    // Not a spinner and not an error: an installation that has never saved
    // the setting is a working state, in the way `freshness_days` is.
    expect(svc.effective()).toBe('standard');
  });

  it('takes the installation default when nothing nearer answers', () => {
    svc.setAppDefault('light');
    expect(svc.effective()).toBe('light');
  });

  it('prefers the scope over the installation', () => {
    svc.setAppDefault('light');
    expect(svc.effective('deep')).toBe('deep');
  });

  it('prefers the pick over both', () => {
    svc.setAppDefault('light');
    svc.pick('standard');
    expect(svc.effective('deep')).toBe('standard');
  });

  it('ignores an empty app default rather than blanking the chip', () => {
    // The server can answer with nothing on an installation that has saved
    // no config. Writing that through would leave every screen showing an
    // empty select and running at whatever the route decided.
    svc.setAppDefault('deep');
    svc.setAppDefault(undefined);
    svc.setAppDefault(null);
    expect(svc.effective()).toBe('deep');
  });

  it('says whether the depth was picked or inherited', () => {
    expect(svc.overridden()).toBeFalse();
    svc.pick('deep');
    expect(svc.overridden()).toBeTrue();
    svc.pick(null);
    expect(svc.overridden()).toBeFalse();
  });

  it('forgets the pick on navigation', async () => {
    // The point of the whole thing. Going deep to work one account must not
    // silently become the setting that researches the next two hundred.
    svc.pick('deep');
    expect(svc.effective('light')).toBe('deep');

    await router.navigateByUrl('/somewhere-else');
    expect(svc.overridden()).toBeFalse();
    expect(svc.effective('light')).toBe('light');
  });

  it('keeps the installation default across navigation', async () => {
    // Only the pick is per-visit. Re-fetching the installation's answer on
    // every route change would be a request per navigation for a figure that
    // changes about once.
    svc.setAppDefault('deep');
    await router.navigateByUrl('/somewhere-else');
    expect(svc.effective()).toBe('deep');
  });
});
