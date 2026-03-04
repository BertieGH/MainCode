import { Routes } from '@angular/router';
import { MainLayoutComponent } from './shared/components/main-layout/main-layout.component';
import { authGuard } from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';
import { managerGuard } from './core/guards/manager.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login.component')
      .then(m => m.LoginComponent)
  },
  {
    path: 'register',
    loadComponent: () => import('./features/auth/register/register.component')
      .then(m => m.RegisterComponent)
  },
  {
    path: '',
    component: MainLayoutComponent,
    canActivate: [authGuard],
    children: [
      {
        path: '',
        redirectTo: 'surveys',
        pathMatch: 'full'
      },
      {
        path: 'question-bank',
        loadChildren: () => import('./features/question-bank/question-bank.routes')
          .then(m => m.QUESTION_BANK_ROUTES)
      },
      {
        path: 'surveys',
        loadChildren: () => import('./features/survey-builder/survey-builder.routes')
          .then(m => m.SURVEY_BUILDER_ROUTES)
      },
      {
        path: 'execute',
        loadChildren: () => import('./features/survey-execution/survey-execution.routes')
          .then(m => m.SURVEY_EXECUTION_ROUTES)
      },
      {
        path: 'analytics',
        canActivate: [managerGuard],
        loadChildren: () => import('./features/analytics/analytics.routes')
          .then(m => m.analyticsRoutes)
      },
      {
        path: 'field-mapping',
        canActivate: [managerGuard],
        loadChildren: () => import('./features/field-mapping/field-mapping.routes')
          .then(m => m.fieldMappingRoutes)
      },
      {
        path: 'users',
        canActivate: [adminGuard],
        loadChildren: () => import('./features/user-management/user-management.routes')
          .then(m => m.USER_MANAGEMENT_ROUTES)
      }
    ]
  },
  {
    path: '**',
    redirectTo: 'login'
  }
];
