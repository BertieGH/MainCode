import { Routes } from '@angular/router';
import { DashboardComponent } from './components/dashboard/dashboard.component';
import { SurveyAnalyticsComponent } from './components/survey-analytics/survey-analytics.component';
import { ClientHistoryComponent } from './components/client-history/client-history.component';

export const analyticsRoutes: Routes = [
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full'
  },
  {
    path: 'dashboard',
    component: DashboardComponent,
    title: 'Analytics Dashboard'
  },
  {
    path: 'survey/:id',
    component: SurveyAnalyticsComponent,
    title: 'Survey Analytics'
  },
  {
    path: 'client/:id',
    component: ClientHistoryComponent,
    title: 'Client Survey History'
  }
];
