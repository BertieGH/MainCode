import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { LoginComponent } from './features/login/login.component';
import { LayoutComponent } from './shared/components/layout/layout.component';
import { DashboardComponent } from './features/dashboard/dashboard.component';
import { UsersComponent } from './features/users/users.component';
import { SocialAccountsComponent } from './features/social-accounts/social-accounts.component';
import { KeywordsComponent } from './features/keywords/keywords.component';
import { ProspectsComponent } from './features/prospects/prospects.component';
import { StrategiesComponent } from './features/strategies/strategies.component';
import { DailyListComponent } from './features/daily-list/daily-list.component';
import { AnalyticsComponent } from './features/analytics/analytics.component';
import { TenantsComponent } from './features/tenants/tenants.component';
import { SignalsComponent } from './features/signals/signals.component';
import { AccountConfigComponent } from './features/account-config/account-config.component';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  {
    path: '',
    component: LayoutComponent,
    canActivate: [authGuard],
    children: [
      { path: 'dashboard', component: DashboardComponent },
      { path: 'prospects', component: ProspectsComponent },
      { path: 'daily-list', component: DailyListComponent },
      { path: 'strategies', component: StrategiesComponent },
      { path: 'social-accounts', redirectTo: 'account-config', pathMatch: 'full' },
      { path: 'account-config', component: AccountConfigComponent },
      { path: 'signals', component: SignalsComponent },
      { path: 'analytics', component: AnalyticsComponent },
      { path: 'keywords', component: KeywordsComponent },
      { path: 'users', component: UsersComponent },
      { path: 'tenants', component: TenantsComponent },
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
    ]
  },
  { path: '**', redirectTo: 'login' }
];
