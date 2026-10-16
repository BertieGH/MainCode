import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, throwError } from 'rxjs';

import { AuthService } from './auth.service';

/** Where a role with nothing else open lands. Every role can at least view lists. */
const HOME = '/lists';

/**
 * Signed in, and allowed to see this screen.
 *
 * A route says what it needs in `data`: `module` (any level but `none`) or
 * `admin: true`. A route that names neither only needs a signed-in user.
 * Turned away from a screen, a person goes home rather than to a blank page —
 * the menu already hides what they cannot open, so arriving here means a
 * stale bookmark, not a mistake worth an error screen.
 */
export const authGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.load().pipe(
    map((me) => {
      if (!me) return router.createUrlTree(['/login'], { queryParams: { next: state.url } });
      if (route.data['admin'] && !auth.isAdmin()) return router.parseUrl(HOME);
      const module = route.data['module'] as string | undefined;
      if (module && !auth.canSee(module)) return router.parseUrl(HOME);
      return true;
    }),
  );
};

/** The sign-in page, only for somebody not signed in. */
export const signedOutGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.load().pipe(map((me) => (me ? router.parseUrl(HOME) : true)));
};

/**
 * A 401 from any API call means the session ended — expired, a password
 * changed elsewhere, or an admin deactivated the account. Go to sign-in and
 * come back to the same page afterwards.
 *
 * Not for the calls that *ask* whether anyone is signed in: a 401 there is
 * the answer, not an event.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  // The server refuses a write that carries a session without this header:
  // another site can make a browser send our cookie, but cannot add a custom
  // header without a CORS preflight it would fail (`main.py`).
  if (req.url.startsWith('/api/')) req = req.clone({ setHeaders: { 'X-Gen360': '1' } });
  return next(req).pipe(
    catchError((err: unknown) => {
      const asking = req.url.startsWith('/api/auth/');
      // Only a session that *was* known to exist can end. Before the first
      // "who am I" answers, a 401 is the shell racing the guard on the very
      // first page — and the guard, which knows the page being opened, is the
      // one that should send it to sign-in with the right `next`.
      const hadSession = auth.me() != null;
      if (err instanceof HttpErrorResponse && err.status === 401 && !asking && hadSession) {
        auth.signedOut();
        const here = router.url.startsWith('/login') ? undefined : router.url;
        void router.navigate(['/login'], { queryParams: here ? { next: here } : {} });
      }
      return throwError(() => err);
    }),
  );
};
