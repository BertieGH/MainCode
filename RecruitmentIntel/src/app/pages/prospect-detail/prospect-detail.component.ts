import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Prospect, ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-prospect-detail',
  standalone: true,
  imports: [
    CommonModule, RouterLink,
    MatCardModule, MatTableModule, MatButtonModule, MatIconModule,
    MatChipsModule, MatProgressBarModule, MatProgressSpinnerModule,
    MatTooltipModule, MatMenuModule, MatSnackBarModule
  ],
  templateUrl: './prospect-detail.component.html',
  styleUrl: './prospect-detail.component.scss'
})
export class ProspectDetailComponent implements OnInit, OnDestroy {
  listId = '';
  list: ProspectList | undefined;
  prospects: Prospect[] = [];
  displayedColumns = ['companyName', 'industry', 'fundingRound', 'amount', 'website', 'linkedin', 'enrichmentStatus', 'jobCrawlStatus', 'jobCount', 'actions'];

  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private pollStart = 0;
  private readonly POLL_MS = 3000;
  private readonly POLL_MAX_MS = 10 * 60 * 1000;

  constructor(
    private route: ActivatedRoute,
    private snackBar: MatSnackBar,
    private api: ApiService,
  ) {
    this.listId = this.route.snapshot.paramMap.get('id') || '';
  }

  ngOnInit() {
    this.loadList();
    this.loadProspects();
  }

  ngOnDestroy() {
    this.stopPolling();
  }

  loadList() {
    if (!this.listId) return;
    this.api.getProspectList(this.listId).subscribe({
      next: (data) => this.list = data,
      error: () => this.snackBar.open('Failed to load list', 'OK', { duration: 3000 })
    });
  }

  loadProspects() {
    if (!this.listId) return;
    this.api.getProspects(this.listId).subscribe({
      next: (data) => {
        this.prospects = data;
        if (this.anyPending()) this.startPolling();
        else this.stopPolling();
      },
      error: () => this.snackBar.open('Failed to load prospects', 'OK', { duration: 3000 })
    });
  }

  anyPending(): boolean {
    return this.prospects.some(p =>
      p.enrichmentStatus === 'pending' || p.jobCrawlStatus === 'pending'
    );
  }

  isRowPending(p: Prospect): boolean {
    return p.enrichmentStatus === 'pending' || p.jobCrawlStatus === 'pending';
  }

  private startPolling() {
    if (this.pollHandle) return;
    this.pollStart = Date.now();
    this.pollHandle = setInterval(() => {
      if (Date.now() - this.pollStart > this.POLL_MAX_MS) {
        this.stopPolling();
        return;
      }
      this.api.getProspects(this.listId).subscribe({
        next: (data) => {
          this.prospects = data;
          if (!this.anyPending()) this.stopPolling();
        },
      });
    }, this.POLL_MS);
  }

  private stopPolling() {
    if (this.pollHandle) {
      clearInterval(this.pollHandle);
      this.pollHandle = null;
    }
  }

  get enrichedCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'done').length; }
  get pendingCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'pending').length; }
  get failedCount(): number { return this.prospects.filter(p => p.enrichmentStatus === 'failed').length; }
  get crawledCount(): number { return this.prospects.filter(p => p.jobCrawlStatus === 'done').length; }
  get emptyCount(): number { return this.prospects.filter(p => p.jobCrawlStatus === 'empty').length; }
  get totalJobs(): number { return this.prospects.reduce((sum, p) => sum + p.jobCount, 0); }
  get enrichPercent(): number { return this.prospects.length > 0 ? (this.enrichedCount / this.prospects.length) * 100 : 0; }
  get crawlPercent(): number { return this.prospects.length > 0 ? (this.crawledCount / this.prospects.length) * 100 : 0; }

  formatAmount(amount: number): string {
    if (amount >= 1000000000) return '$' + (amount / 1000000000).toFixed(1) + 'B';
    if (amount >= 1000000) return '$' + (amount / 1000000).toFixed(0) + 'M';
    return '$' + amount;
  }

  enrichAll(force = false) {
    if (force && !confirm(`Re-enrich every prospect (${this.prospects.length} rows), including ones already 'done'? This is useful after changing LLM provider or model settings.`)) {
      return;
    }
    this.snackBar.open(
      force ? 'Re-enriching all prospects…' : 'Enrichment started for pending prospects…',
      '', { duration: 2000 }
    );
    this.startPolling();
    this.api.enrichList(this.listId, force).subscribe({
      next: () => {
        this.snackBar.open('Enrichment queued — watch the progress bar', 'OK', { duration: 3000 });
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue enrichment', 'OK', { duration: 3000 })
    });
  }

  crawlAll(force = false) {
    if (force && !confirm(`Re-crawl jobs for every enriched prospect (deletes prior Job rows and cached careers URLs first)? Use this after changing LLM / crawl settings.`)) {
      return;
    }
    this.snackBar.open(
      force ? 'Re-crawling jobs for all enriched prospects…' : 'Job crawl started for enriched prospects…',
      '', { duration: 2000 }
    );
    this.startPolling();
    this.api.crawlJobsForList(this.listId, force).subscribe({
      next: () => {
        this.snackBar.open('Job crawl queued — watch the progress bar', 'OK', { duration: 3000 });
        this.loadProspects();
      },
      error: () => this.snackBar.open('Failed to queue job crawl', 'OK', { duration: 3000 })
    });
  }

  enrichOne(prospect: Prospect) {
    this.snackBar.open(`Enriching ${prospect.companyName}…`, '', { duration: 1500 });
    // Optimistic: mark row pending so spinner shows immediately
    const idx = this.prospects.findIndex(p => p.id === prospect.id);
    if (idx > -1) this.prospects[idx] = { ...this.prospects[idx], enrichmentStatus: 'pending' };
    this.startPolling();
    this.api.enrichProspect(prospect.id).subscribe({
      next: (updated) => {
        if (idx > -1) {
          this.prospects[idx] = {
            ...this.prospects[idx],
            website: updated.website,
            linkedinUrl: updated.linkedinUrl,
            enrichmentStatus: updated.enrichmentStatus,
            enrichmentStrategy: updated.enrichmentStrategy,
            enrichmentError: updated.enrichmentError,
          };
        }
        this.snackBar.open(`${prospect.companyName} enrichment ${updated.enrichmentStatus}`, 'OK', { duration: 2500 });
        if (!this.anyPending()) this.stopPolling();
      },
      error: () => this.snackBar.open('Enrichment failed', 'OK', { duration: 3000 })
    });
  }

  crawlOne(prospect: Prospect, force = false) {
    this.snackBar.open(
      force ? `Re-crawling ${prospect.companyName}…` : `Crawling jobs for ${prospect.companyName}…`,
      '', { duration: 1500 }
    );
    const idx = this.prospects.findIndex(p => p.id === prospect.id);
    if (idx > -1) this.prospects[idx] = { ...this.prospects[idx], jobCrawlStatus: 'pending' };
    this.startPolling();
    this.api.crawlJobsForProspect(prospect.id, force).subscribe({
      next: (res) => {
        if (idx > -1) {
          this.prospects[idx] = {
            ...this.prospects[idx],
            careersUrl: res.careersUrl,
            jobCrawlStatus: res.jobCrawlStatus,
            jobCrawlStrategy: res.jobCrawlStrategy,
            jobCrawlRawCount: res.jobCrawlRawCount ?? 0,
            jobCrawlError: res.jobCrawlError,
            jobCount: res.jobsFound ?? this.prospects[idx].jobCount,
          };
        }
        const msg = res.jobCrawlStatus === 'empty'
          ? `${prospect.companyName}: careers page found but 0 listings`
          : `${prospect.companyName}: found ${res.jobsFound ?? 0} jobs`;
        this.snackBar.open(msg, 'OK', { duration: 3500 });
        if (!this.anyPending()) this.stopPolling();
      },
      error: () => this.snackBar.open('Job crawl failed', 'OK', { duration: 3000 })
    });
  }

  removeProspect(prospect: Prospect) {
    this.api.removeProspect(this.listId, prospect.id).subscribe({
      next: () => this.prospects = this.prospects.filter(p => p.id !== prospect.id),
      error: () => this.snackBar.open('Failed to remove prospect', 'OK', { duration: 3000 })
    });
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'done': return 'check_circle';
      case 'pending': return 'hourglass_empty';
      case 'failed': return 'error';
      case 'empty': return 'inbox';
      default: return 'radio_button_unchecked';
    }
  }

  getStatusColor(status: string): string {
    switch (status) {
      case 'done': return '#4caf50';
      case 'pending': return '#2196f3';
      case 'failed': return '#f44336';
      case 'empty': return '#ff9800';
      default: return '#ccc';
    }
  }

  enrichmentTooltip(p: Prospect): string {
    const parts: string[] = [p.enrichmentStatus];
    if (p.enrichmentStrategy) parts.push(`via ${p.enrichmentStrategy}`);
    if (p.enrichmentError) parts.push(p.enrichmentError);
    return parts.join(' — ');
  }

  crawlTooltip(p: Prospect): string {
    const parts: string[] = [p.jobCrawlStatus];
    if (p.jobCrawlStrategy) parts.push(`via ${p.jobCrawlStrategy}`);
    if (p.jobCrawlRawCount) parts.push(`raw: ${p.jobCrawlRawCount} scraped`);
    if (p.jobCrawlError) parts.push(p.jobCrawlError);
    return parts.join(' — ');
  }
}
