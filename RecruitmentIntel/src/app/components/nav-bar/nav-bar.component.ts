import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-nav-bar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, MatToolbarModule, MatButtonModule, MatIconModule],
  template: `
    <mat-toolbar color="primary" class="nav-toolbar">
      <div class="nav-brand">
        <mat-icon>radar</mat-icon>
        <span class="brand-text">Recruitment Intelligence</span>
      </div>
      <div class="nav-links">
        <a mat-button routerLink="/signals" routerLinkActive="active-link">
          <mat-icon>rss_feed</mat-icon> Signal Log
        </a>
        <a mat-button routerLink="/news-log" routerLinkActive="active-link">
          <mat-icon>article</mat-icon> News Log
        </a>
        <a mat-button routerLink="/prospects" routerLinkActive="active-link">
          <mat-icon>list_alt</mat-icon> Prospects
        </a>
        <a mat-button routerLink="/outreach" routerLinkActive="active-link">
          <mat-icon>work</mat-icon> Outreach
        </a>
      </div>
      <span class="spacer"></span>
      <div class="nav-actions">
        <a mat-icon-button routerLink="/feeds" routerLinkActive="active-link" matTooltip="Feed Manager">
          <mat-icon>dynamic_feed</mat-icon>
        </a>
        <a mat-icon-button routerLink="/settings" routerLinkActive="active-link" matTooltip="Settings">
          <mat-icon>settings</mat-icon>
        </a>
      </div>
    </mat-toolbar>
  `,
  styles: [`
    .nav-toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      position: sticky;
      top: 0;
      z-index: 1000;
    }
    .nav-brand {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-right: 24px;
    }
    .brand-text { font-size: 18px; font-weight: 500; }
    .nav-links { display: flex; gap: 4px; }
    .nav-links a { color: rgba(255,255,255,0.85); }
    .nav-links a mat-icon { margin-right: 4px; font-size: 20px; height: 20px; width: 20px; }
    .spacer { flex: 1; }
    .nav-actions a { color: rgba(255,255,255,0.85); }
    .active-link {
      color: white !important;
      background: rgba(255,255,255,0.15);
      border-radius: 4px;
    }
  `]
})
export class NavBarComponent {}
