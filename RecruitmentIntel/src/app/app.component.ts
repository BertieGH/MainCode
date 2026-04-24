import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { NavBarComponent } from './components/nav-bar/nav-bar.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, NavBarComponent],
  template: `
    <app-nav-bar />
    <main class="main-content">
      <router-outlet />
    </main>
  `,
  styles: [`
    .main-content {
      padding: 24px 32px;
      max-width: 1400px;
      margin: 0 auto;
      background: #f5f5f5;
      min-height: calc(100vh - 64px);
    }
  `]
})
export class AppComponent {}
