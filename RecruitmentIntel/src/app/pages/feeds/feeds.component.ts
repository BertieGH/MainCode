import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { FeedSource } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-feeds',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatFormFieldModule,
    MatInputModule, MatSelectModule, MatChipsModule, MatSlideToggleModule, MatSnackBarModule, MatTooltipModule
  ],
  templateUrl: './feeds.component.html',
  styleUrl: './feeds.component.scss'
})
export class FeedsComponent implements OnInit {
  feeds: FeedSource[] = [];
  showForm = false;
  editingId: string | null = null;

  formName = '';
  formUrl = '';
  formType = 'Google News';
  formKeywords = '';
  feedTypes = ['Google News', 'HN RSS', 'Custom', 'Crunchbase'];

  constructor(private snackBar: MatSnackBar, private api: ApiService) {}

  ngOnInit() {
    this.loadFeeds();
  }

  loadFeeds() {
    this.api.getFeeds().subscribe({
      next: (data) => this.feeds = data,
      error: () => this.snackBar.open('Failed to load feeds', 'OK', { duration: 3000 })
    });
  }

  toggleActive(feed: FeedSource) {
    const newActive = !feed.isActive;
    this.api.updateFeed(feed.id, { isActive: newActive }).subscribe({
      next: (updated) => {
        const idx = this.feeds.findIndex(f => f.id === feed.id);
        if (idx > -1) this.feeds[idx] = updated;
      },
      error: () => this.snackBar.open('Failed to update feed', 'OK', { duration: 3000 })
    });
  }

  editFeed(feed: FeedSource) {
    this.editingId = feed.id;
    this.formName = feed.name;
    this.formUrl = feed.url;
    this.formType = feed.feedType;
    this.formKeywords = feed.keywords.join(', ');
    this.showForm = true;
  }

  deleteFeed(id: string) {
    this.api.deleteFeed(id).subscribe({
      next: () => {
        this.feeds = this.feeds.filter(f => f.id !== id);
        this.snackBar.open('Feed deleted', 'OK', { duration: 2000 });
      },
      error: () => this.snackBar.open('Failed to delete feed', 'OK', { duration: 3000 })
    });
  }

  saveFeed() {
    if (!this.formName.trim() || !this.formUrl.trim()) return;
    const keywords = this.formKeywords.split(',').map(k => k.trim()).filter(k => k);
    const payload = {
      name: this.formName,
      url: this.formUrl,
      feedType: this.formType,
      keywords,
    };

    if (this.editingId) {
      this.api.updateFeed(this.editingId, payload).subscribe({
        next: (updated) => {
          const idx = this.feeds.findIndex(f => f.id === this.editingId);
          if (idx > -1) this.feeds[idx] = updated;
          this.snackBar.open('Feed updated', 'OK', { duration: 2000 });
          this.cancelForm();
        },
        error: () => this.snackBar.open('Failed to update feed', 'OK', { duration: 3000 })
      });
    } else {
      this.api.createFeed(payload).subscribe({
        next: (created) => {
          this.feeds.unshift(created);
          this.snackBar.open('Feed created', 'OK', { duration: 2000 });
          this.cancelForm();
        },
        error: () => this.snackBar.open('Failed to create feed', 'OK', { duration: 3000 })
      });
    }
  }

  cancelForm() {
    this.showForm = false;
    this.editingId = null;
    this.formName = '';
    this.formUrl = '';
    this.formType = 'Google News';
    this.formKeywords = '';
  }

  newFeed() {
    this.cancelForm();
    this.showForm = true;
  }

  addSuggested() {
    this.api.addSuggestedFeeds().subscribe({
      next: (added) => {
        if (added.length === 0) {
          this.snackBar.open('All suggested feeds are already added', 'OK', { duration: 3000 });
          return;
        }
        this.feeds = [...added, ...this.feeds];
        this.snackBar.open(`Added ${added.length} suggested feed${added.length === 1 ? '' : 's'}`, 'OK', { duration: 3000 });
      },
      error: () => this.snackBar.open('Failed to add suggested feeds', 'OK', { duration: 3000 })
    });
  }
}
