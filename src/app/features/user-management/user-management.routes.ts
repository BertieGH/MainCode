import { Routes } from '@angular/router';

export const USER_MANAGEMENT_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./components/user-list/user-list.component')
      .then(m => m.UserListComponent)
  },
  {
    path: 'new',
    loadComponent: () => import('./components/user-form/user-form.component')
      .then(m => m.UserFormComponent)
  },
  {
    path: 'edit/:id',
    loadComponent: () => import('./components/user-form/user-form.component')
      .then(m => m.UserFormComponent)
  }
];
