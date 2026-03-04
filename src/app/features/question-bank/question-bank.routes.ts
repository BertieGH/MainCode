import { Routes } from '@angular/router';

export const QUESTION_BANK_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./components/question-list/question-list.component')
      .then(m => m.QuestionListComponent)
  },
  {
    path: 'new',
    loadComponent: () => import('./components/question-form/question-form.component')
      .then(m => m.QuestionFormComponent)
  },
  {
    path: 'edit/:id',
    loadComponent: () => import('./components/question-form/question-form.component')
      .then(m => m.QuestionFormComponent)
  },
  {
    path: 'categories',
    loadComponent: () => import('./components/category-management/category-management.component')
      .then(m => m.CategoryManagementComponent)
  }
];
