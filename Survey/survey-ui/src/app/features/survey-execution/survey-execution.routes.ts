import { Routes } from '@angular/router';

export const SURVEY_EXECUTION_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./components/survey-select/survey-select.component')
      .then(m => m.SurveySelectComponent)
  },
  {
    path: ':id',
    loadComponent: () => import('./components/survey-response/survey-response.component')
      .then(m => m.SurveyResponseComponent)
  }
];
