import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { environment } from '../../../environments/environment';
import { AuthService } from '../services/auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  const headers: Record<string, string> = {
    'X-API-Key': environment.apiKey
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const clonedRequest = req.clone({ setHeaders: headers });
  return next(clonedRequest);
};
