import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'lists', pathMatch: 'full' },
  {
    path: 'lists',
    loadComponent: () => import('./lists/lists.component').then((m) => m.ListsComponent),
  },
  {
    path: 'lists/:id',
    loadComponent: () =>
      import('./lists/list-detail.component').then((m) => m.ListDetailComponent),
  },
  {
    path: 'accounts/:id',
    loadComponent: () =>
      import('./accounts/account-detail.component').then((m) => m.AccountDetailComponent),
  },
  {
    path: 'queues',
    loadComponent: () => import('./queues/queues.component').then((m) => m.QueuesComponent),
  },
  {
    path: 'queues/:id',
    loadComponent: () =>
      import('./queues/queue-detail.component').then((m) => m.QueueDetailComponent),
  },
  {
    path: 'campaigns',
    loadComponent: () =>
      import('./campaigns/campaigns.component').then((m) => m.CampaignsComponent),
  },
  {
    path: 'campaigns/:id',
    loadComponent: () =>
      import('./campaigns/campaign-detail.component').then((m) => m.CampaignDetailComponent),
  },
  {
    path: 'prep',
    loadComponent: () => import('./prep/prep.component').then((m) => m.PrepComponent),
  },
  {
    path: 'prep/:id',
    loadComponent: () =>
      import('./prep/prep-detail.component').then((m) => m.PrepDetailComponent),
  },
  {
    path: 'settings',
    children: [
      { path: '', redirectTo: 'setup', pathMatch: 'full' },
      {
        path: 'setup',
        loadComponent: () => import('./settings/setup.component').then((m) => m.SetupComponent),
      },
      {
        path: 'services',
        loadComponent: () =>
          import('./settings/services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'icp-profiles',
        loadComponent: () =>
          import('./settings/icp-profiles.component').then((m) => m.IcpProfilesComponent),
      },
      {
        path: 'writing',
        loadComponent: () =>
          import('./settings/writing-samples.component').then((m) => m.WritingSamplesComponent),
      },
      {
        path: 'monitoring',
        loadComponent: () =>
          import('./settings/monitoring.component').then((m) => m.MonitoringComponent),
      },
      {
        path: 'scoring',
        loadComponent: () =>
          import('./settings/scoring.component').then((m) => m.ScoringComponent),
      },
      {
        path: 'models',
        loadComponent: () =>
          import('./settings/model-config.component').then((m) => m.ModelConfigComponent),
      },
      {
        path: 'rules',
        loadComponent: () =>
          import('./settings/sales-rules.component').then((m) => m.SalesRulesComponent),
      },
      {
        path: 'signal-types',
        loadComponent: () =>
          import('./settings/signal-types.component').then((m) => m.SignalTypesComponent),
      },
      {
        path: 'prompts',
        loadComponent: () =>
          import('./settings/prompts.component').then((m) => m.PromptsComponent),
      },
      // Merged into Setup. Kept as a redirect so bookmarks and the links
      // this app printed in its own copy do not 404.
      { path: 'integrations', redirectTo: 'setup', pathMatch: 'full' },
    ],
  },
];
