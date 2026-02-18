import { Routes } from '@angular/router';

export const SURVEY_BUILDER_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./components/survey-list/survey-list.component')
      .then(m => m.SurveyListComponent)
  },
  {
    path: 'new',
    loadComponent: () => import('./components/survey-form/survey-form.component')
      .then(m => m.SurveyFormComponent)
  },
  {
    path: ':id/edit',
    loadComponent: () => import('./components/survey-form/survey-form.component')
      .then(m => m.SurveyFormComponent)
  },
  {
    path: ':id/builder',
    loadComponent: () => import('./components/survey-builder/survey-builder.component')
      .then(m => m.SurveyBuilderComponent)
  },
  {
    path: ':id/preview',
    loadComponent: () => import('./components/survey-preview/survey-preview.component')
      .then(m => m.SurveyPreviewComponent)
  }
];
