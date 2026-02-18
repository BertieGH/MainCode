import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { TopbarComponent } from '../topbar/topbar.component';

@Component({
  selector: 'app-main-layout',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent, TopbarComponent],
  template: `
    <app-sidebar></app-sidebar>
    <main class="main">
      <app-topbar></app-topbar>
      <div class="content">
        <router-outlet></router-outlet>
      </div>
    </main>
  `,
  styles: [`
    .main {
      margin-left: 260px;
      min-height: 100vh;
    }

    .content {
      padding: 28px 32px;
    }
  `]
})
export class MainLayoutComponent {}
