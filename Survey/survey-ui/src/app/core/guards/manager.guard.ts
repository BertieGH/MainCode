import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { UserRole } from '../models/user.model';

export const managerGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.hasRole(UserRole.Admin) || authService.hasRole(UserRole.Manager)) {
    return true;
  }

  return router.createUrlTree(['/surveys']);
};
