import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatExpansionModule } from '@angular/material/expansion';
import { SelectionModel } from '@angular/cdk/collections';
import { Signal, ProspectList, IngestionRun } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-signal-log',
  standalone: true,
  imports: [
    CommonModule, RouterLink, FormsModule,
    MatCardModule, MatTableModule, MatCheckboxModule, MatSelectModule,
    MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule,
    MatChipsModule, MatSortModule, MatDialogModule, MatSnackBarModule,
    MatTooltipModule, MatProgressSpinnerModule, MatExpansionModule
  ],
  templateUrl: './signal-log.component.html',
  styleUrl: './signal-log.component.scss'
})
export class SignalLogComponent implements OnInit {
  signals: Signal[] = [];
  filteredSignals: Signal[] = [];
  selection = new SelectionModel<Signal>(true, []);
  prospectLists: ProspectList[] = [];
  loading = false;
  ingesting = false;
  recentRuns: IngestionRun[] = [];
  expandedRunId: string | null = null;

  displayedColumns = ['select', 'companyName', 'industry', 'fundingRound', 'amount', 'location', 'date', 'source'];

  industries = ['All', 'AI', 'Fintech', 'SaaS', 'Cybersecurity', 'HealthTech', 'EdTech', 'CleanTech', 'Other'];
  fundingRounds = ['All', 'Pre-Seed', 'Seed', 'Series A', 'Series B', 'Series C', 'Series D', 'Growth', 'Other'];

  filterIndustry = 'All';
  filterRound = 'All';
  filterAmountMin = '';
  filterAmountMax = '';
  filterLocation = '';
  filterDateFrom = '';
  filterDateTo = '';
  selectedListId = '';
  newListName = '';
  showNewListInput = false;

  constructor(private snackBar: MatSnackBar, private api: ApiService) {}

  ngOnInit() {
    this.loadSignals();
    this.loadLists();
    this.loadRuns();
  }

  loadRuns() {
    this.api.getIngestionRuns(5).subscribe({
      next: (runs) => this.recentRuns = runs,
    });
  }

  runDurationSeconds(run: IngestionRun): number | null {
    if (!run.finishedAt) return null;
    return Math.max(0, Math.round((+new Date(run.finishedAt) - +new Date(run.startedAt)) / 1000));
  }

  runStatusIcon(status: string): string {
    switch (status) {
      case 'ok': return 'check_circle';
      case 'warning': return 'warning';
      case 'error': return 'error';
      case 'running': return 'hourglass_empty';
      default: return 'help_outline';
    }
  }

  runStatusColor(status: string): string {
    switch (status) {
      case 'ok': return '#4caf50';
      case 'warning': return '#ff9800';
      case 'error': return '#f44336';
      case 'running': return '#1976d2';
      default: return '#999';
    }
  }

  loadSignals() {
    this.loading = true;
    const filters: any = {};
    if (this.filterIndustry !== 'All') filters.industry = this.filterIndustry;
    if (this.filterRound !== 'All') filters.funding_round = this.filterRound;
    if (this.filterAmountMin) filters.amount_min = +this.filterAmountMin * 1000000;
    if (this.filterAmountMax) filters.amount_max = +this.filterAmountMax * 1000000;
    if (this.filterLocation) filters.location = this.filterLocation;
    if (this.filterDateFrom) filters.date_from = this.filterDateFrom;
    if (this.filterDateTo) filters.date_to = this.filterDateTo;

    this.api.getSignals(filters).subscribe({
      next: (data) => {
        this.signals = data;
        this.filteredSignals = data;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.snackBar.open('Failed to load signals', 'OK', { duration: 3000 });
      }
    });
  }

  loadLists() {
    this.api.getProspectLists().subscribe({
      next: (data) => this.prospectLists = data,
    });
  }

  applyFilters() {
    this.loadSignals();
  }

  ingestNow() {
    this.ingesting = true;
    this.api.triggerIngest().subscribe({
      next: (res) => {
        this.ingesting = false;
        // Refresh runs + auto-expand the one we just created
        this.loadRuns();
        if (res?.runId) this.expandedRunId = res.runId;

        if (res?.status === 'error') {
          this.snackBar.open(res.message || 'Ingestion failed — see details below', 'OK', { duration: 5000 });
          return;
        }
        if (res?.status === 'warning') {
          this.snackBar.open(res.message || 'Nothing ingested', 'OK', { duration: 4000 });
          return;
        }
        const added = res?.totalNewSignals ?? 0;
        const skipped = res?.totalSkipped ?? 0;
        this.snackBar.open(
          `Ingestion complete — ${added} new signal${added === 1 ? '' : 's'}, ${skipped} skipped`,
          'OK', { duration: 4000 }
        );
        this.loadSignals();
      },
      error: () => {
        this.ingesting = false;
        this.snackBar.open('Ingestion request failed', 'OK', { duration: 3000 });
      }
    });
  }

  clearFilters() {
    this.filterIndustry = 'All';
    this.filterRound = 'All';
    this.filterAmountMin = '';
    this.filterAmountMax = '';
    this.filterLocation = '';
    this.filterDateFrom = '';
    this.filterDateTo = '';
    this.loadSignals();
  }

  isAllSelected() {
    return this.selection.selected.length === this.filteredSignals.length;
  }

  toggleAllRows() {
    this.isAllSelected() ? this.selection.clear() : this.filteredSignals.forEach(row => this.selection.select(row));
  }

  formatAmount(amount: number): string {
    if (amount >= 1000000000) return '$' + (amount / 1000000000).toFixed(1) + 'B';
    if (amount >= 1000000) return '$' + (amount / 1000000).toFixed(0) + 'M';
    if (amount >= 1000) return '$' + (amount / 1000).toFixed(0) + 'K';
    return '$' + amount;
  }

  sortData(sort: Sort) {
    const data = [...this.filteredSignals];
    if (!sort.active || sort.direction === '') {
      this.filteredSignals = data;
      return;
    }
    this.filteredSignals = data.sort((a, b) => {
      const isAsc = sort.direction === 'asc';
      switch (sort.active) {
        case 'companyName': return compare(a.companyName, b.companyName, isAsc);
        case 'industry': return compare(a.industry, b.industry, isAsc);
        case 'fundingRound': return compare(a.fundingRound, b.fundingRound, isAsc);
        case 'amount': return compare(a.amount, b.amount, isAsc);
        case 'date': return compare(a.date, b.date, isAsc);
        default: return 0;
      }
    });
  }

  getTotalFunding(): number {
    return this.filteredSignals.reduce((sum, s) => sum + s.amount, 0);
  }

  getUniqueIndustries(): number {
    return new Set(this.filteredSignals.map(s => s.industry)).size;
  }

  addToList() {
    if (this.selection.selected.length === 0) return;
    const signalIds = this.selection.selected.map(s => s.id);

    if (this.showNewListInput && this.newListName.trim()) {
      // Create new list first, then add signals
      this.api.createProspectList(this.newListName, '').subscribe({
        next: (list) => {
          this.api.addSignalsToList(list.id, signalIds).subscribe({
            next: (res) => {
              this.snackBar.open(this._addResultMessage(res, list.name), 'View', { duration: 4500 });
              this.selection.clear();
              this.showNewListInput = false;
              this.newListName = '';
              this.loadLists();
            },
            error: () => this.snackBar.open('Failed to add signals', 'OK', { duration: 3000 })
          });
        },
        error: () => this.snackBar.open('Failed to create list', 'OK', { duration: 3000 })
      });
    } else if (this.selectedListId) {
      this.api.addSignalsToList(this.selectedListId, signalIds).subscribe({
        next: (res) => {
          const listName = this.prospectLists.find(l => l.id === this.selectedListId)?.name || '';
          this.snackBar.open(this._addResultMessage(res, listName), 'View', { duration: 4500 });
          this.selection.clear();
        },
        error: () => this.snackBar.open('Failed to add signals', 'OK', { duration: 3000 })
      });
    }
  }

  private _addResultMessage(res: { added: any[]; skipped: any[] }, listName: string): string {
    const added = res.added?.length ?? 0;
    const skipped = res.skipped ?? [];
    if (skipped.length === 0) {
      return `Added ${added} companies to "${listName}"`;
    }
    const dupSignal = skipped.filter(s => s.reason === 'dup_signal').length;
    const dupCompany = skipped.filter(s => s.reason === 'dup_company_in_list').length;
    const dupBatch = skipped.filter(s => s.reason === 'dup_company_in_batch').length;
    const parts: string[] = [];
    if (dupCompany) parts.push(`${dupCompany} already on list`);
    if (dupSignal) parts.push(`${dupSignal} same signal`);
    if (dupBatch) parts.push(`${dupBatch} duplicate in selection`);
    return `Added ${added} to "${listName}" — skipped ${skipped.length} (${parts.join(', ')})`;
  }
}

function compare(a: string | number, b: string | number, isAsc: boolean): number {
  return (a < b ? -1 : 1) * (isAsc ? 1 : -1);
}
