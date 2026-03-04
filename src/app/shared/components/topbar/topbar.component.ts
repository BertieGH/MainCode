import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { PageTitleService } from '../../../core/services/page-title.service';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="topbar">
      <div class="topbar-left">
        <h2>{{ pageTitle.title$ | async }}</h2>
        <p *ngIf="(pageTitle.subtitle$ | async) as sub">{{ sub }}</p>
      </div>
      <div class="topbar-right">
        <div class="search-box">
          <span class="material-icons-outlined">search</span>
          <input type="text" placeholder="Search surveys, questions...">
        </div>
        <button class="icon-btn">
          <span class="material-icons-outlined">notifications</span>
          <span class="dot"></span>
        </button>
        <button class="icon-btn">
          <span class="material-icons-outlined">help_outline</span>
        </button>
      </div>
    </div>
  `,
  styles: [`
    .topbar {
      background: #fff;
      padding: 16px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #e5e7eb;
      position: sticky;
      top: 0;
      z-index: 50;
    }

    .topbar-left h2 {
      font-size: 20px;
      font-weight: 600;
      margin: 0;
    }

    .topbar-left p {
      font-size: 13px;
      color: #6b7280;
      margin-top: 2px;
    }

    .topbar-right {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .search-box {
      display: flex;
      align-items: center;
      gap: 8px;
      background: #f3f4f6;
      border-radius: 8px;
      padding: 8px 14px;
      border: 1px solid transparent;
      transition: all 0.2s;
    }

    .search-box:focus-within {
      border-color: #6366f1;
      background: #fff;
    }

    .search-box input {
      border: none;
      background: none;
      outline: none;
      font-size: 13px;
      width: 200px;
      font-family: inherit;
    }

    .search-box .material-icons-outlined {
      font-size: 18px;
      color: #9ca3af;
    }

    .icon-btn {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      border: 1px solid #e5e7eb;
      background: #fff;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      transition: all 0.2s;
    }

    .icon-btn:hover {
      background: #f3f4f6;
    }

    .icon-btn .material-icons-outlined {
      font-size: 20px;
      color: #6b7280;
    }

    .icon-btn .dot {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 8px;
      height: 8px;
      background: #ef4444;
      border-radius: 50%;
      border: 2px solid #fff;
    }
  `]
})
export class TopbarComponent {
  constructor(public pageTitle: PageTitleService) {}
}
