import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'signals', pathMatch: 'full' },
  { path: 'signals', loadComponent: () => import('./pages/signal-log/signal-log.component').then(m => m.SignalLogComponent) },
  { path: 'news-log', loadComponent: () => import('./pages/news-log/news-log.component').then(m => m.NewsLogComponent) },
  { path: 'prospects', loadComponent: () => import('./pages/prospect-lists/prospect-lists.component').then(m => m.ProspectListsComponent) },
  { path: 'prospects/:id', loadComponent: () => import('./pages/prospect-detail/prospect-detail.component').then(m => m.ProspectDetailComponent) },
  { path: 'outreach', loadComponent: () => import('./pages/outreach/outreach.component').then(m => m.OutreachComponent) },
  { path: 'feeds', loadComponent: () => import('./pages/feeds/feeds.component').then(m => m.FeedsComponent) },
  { path: 'settings', loadComponent: () => import('./pages/settings/settings.component').then(m => m.SettingsComponent) },
];
