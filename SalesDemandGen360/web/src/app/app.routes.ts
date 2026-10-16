import { Routes } from '@angular/router';

import { authGuard, signedOutGuard } from './core/auth.guard';

/**
 * Every screen sits under one guarded parent, so a route added later is
 * signed-in by default rather than by remembering to. `data.module` names the
 * role-grid module a screen belongs to (`docs/17`); a role with `none` there is
 * sent home. The server checks every request regardless.
 */
const screens: Routes = [
  { path: '', redirectTo: 'lists', pathMatch: 'full' },
  {
    path: 'lists',
    data: { module: 'lists' },
    loadComponent: () => import('./lists/lists.component').then((m) => m.ListsComponent),
  },
  {
    path: 'lists/:id',
    data: { module: 'lists' },
    loadComponent: () =>
      import('./lists/list-detail.component').then((m) => m.ListDetailComponent),
  },
  {
    path: 'accounts/:id',
    data: { module: 'lists' },
    loadComponent: () =>
      import('./accounts/account-detail.component').then((m) => m.AccountDetailComponent),
  },
  {
    path: 'queues',
    data: { module: 'queues' },
    loadComponent: () => import('./queues/queues.component').then((m) => m.QueuesComponent),
  },
  {
    path: 'queues/:id',
    data: { module: 'queues' },
    loadComponent: () =>
      import('./queues/queue-detail.component').then((m) => m.QueueDetailComponent),
  },
  {
    path: 'campaigns',
    data: { module: 'outreach' },
    loadComponent: () =>
      import('./campaigns/campaigns.component').then((m) => m.CampaignsComponent),
  },
  {
    path: 'campaigns/:id',
    data: { module: 'outreach' },
    loadComponent: () =>
      import('./campaigns/campaign-detail.component').then((m) => m.CampaignDetailComponent),
  },
  {
    path: 'prep',
    data: { module: 'prep' },
    loadComponent: () => import('./prep/prep.component').then((m) => m.PrepComponent),
  },
  {
    path: 'prep/:id',
    data: { module: 'prep' },
    loadComponent: () =>
      import('./prep/prep-detail.component').then((m) => m.PrepDetailComponent),
  },
  {
    path: 'dashboard/cost-health',
    data: { module: 'dashboard' },
    loadComponent: () =>
      import('./dashboard/cost-health.component').then((m) => m.CostHealthComponent),
  },
  {
    path: 'settings',
    children: [
      { path: '', redirectTo: 'setup', pathMatch: 'full' },
      {
        path: 'setup',
        // API keys: admin only.
        data: { admin: true },
        loadComponent: () => import('./settings/setup.component').then((m) => m.SetupComponent),
      },
      {
        path: 'services',
        data: { module: 'content' },
        loadComponent: () =>
          import('./settings/services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'icp-profiles',
        data: { module: 'content' },
        loadComponent: () =>
          import('./settings/icp-profiles.component').then((m) => m.IcpProfilesComponent),
      },
      {
        path: 'writing',
        data: { module: 'content' },
        loadComponent: () =>
          import('./settings/writing-samples.component').then((m) => m.WritingSamplesComponent),
      },
      {
        path: 'scoring',
        data: { module: 'scoring' },
        loadComponent: () =>
          import('./settings/scoring.component').then((m) => m.ScoringComponent),
      },
      {
        path: 'models',
        data: { module: 'models_prompts' },
        loadComponent: () =>
          import('./settings/model-config.component').then((m) => m.ModelConfigComponent),
      },
      {
        path: 'rules',
        data: { module: 'rules_cadences' },
        loadComponent: () =>
          import('./settings/sales-rules.component').then((m) => m.SalesRulesComponent),
      },
      {
        path: 'signal-types',
        data: { module: 'sources_signals' },
        loadComponent: () =>
          import('./settings/signal-types.component').then((m) => m.SignalTypesComponent),
      },
      {
        path: 'prompts',
        data: { module: 'models_prompts' },
        loadComponent: () =>
          import('./settings/prompts.component').then((m) => m.PromptsComponent),
      },
      {
        path: 'users',
        data: { admin: true },
        loadComponent: () => import('./settings/users.component').then((m) => m.UsersComponent),
      },
      {
        path: 'roles',
        data: { admin: true },
        loadComponent: () => import('./settings/roles.component').then((m) => m.RolesComponent),
      },
      // Merged into Setup. Kept as a redirect so bookmarks and the links
      // this app printed in its own copy do not 404.
      { path: 'integrations', redirectTo: 'setup', pathMatch: 'full' },
    ],
  },
];

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [signedOutGuard],
    loadComponent: () => import('./login/login.component').then((m) => m.LoginComponent),
  },
  { path: '', canActivateChild: [authGuard], children: screens },
];
