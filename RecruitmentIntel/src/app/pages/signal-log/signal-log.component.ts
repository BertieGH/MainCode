import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
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
import { SelectionModel } from '@angular/cdk/collections';
import { Signal, ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';
import { InfoDialogComponent } from '../../components/info-dialog/info-dialog.component';
import { SIGNAL_LOG_WORKFLOW } from '../../components/info-dialog/workflows';

@Component({
  selector: 'app-signal-log',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatTableModule, MatCheckboxModule, MatSelectModule,
    MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule,
    MatChipsModule, MatSortModule, MatDialogModule, MatSnackBarModule,
    MatTooltipModule
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

  displayedColumns = ['select', 'companyName', 'industry', 'fundingRound', 'amount', 'location', 'date', 'source', 'actions'];

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

  constructor(private snackBar: MatSnackBar, private api: ApiService, private dialog: MatDialog) {}

  openInfo() {
    this.dialog.open(InfoDialogComponent, { data: SIGNAL_LOG_WORKFLOW, width: '880px', maxWidth: '95vw' });
  }

  ngOnInit() {
    this.loadSignals();
    this.loadLists();
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
        case 'location': return compareWithEmptyLast(a.location, b.location, isAsc);
        case 'sourceTitle': return compareWithEmptyLast(a.sourceTitle, b.sourceTitle, isAsc);
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

  deleteSignal(signal: Signal, event?: MouseEvent) {
    event?.stopPropagation();
    if (!confirm(`Delete signal "${signal.companyName}"?`)) return;
    this.api.deleteSignal(signal.id).subscribe({
      next: () => {
        this.signals = this.signals.filter(s => s.id !== signal.id);
        this.applyFilters();
        this.selection.deselect(signal);
        this.snackBar.open(`Deleted "${signal.companyName}"`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Failed to delete signal', 'OK', { duration: 3000 })
    });
  }

  deleteSelected() {
    const ids = this.selection.selected.map(s => s.id);
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} selected signal${ids.length === 1 ? '' : 's'}?`)) return;
    this.api.bulkDeleteSignals(ids).subscribe({
      next: (res) => {
        const deletedSet = new Set(ids);
        this.signals = this.signals.filter(s => !deletedSet.has(s.id));
        this.selection.clear();
        this.applyFilters();
        this.snackBar.open(`Deleted ${res.deleted} signal${res.deleted === 1 ? '' : 's'}`, 'OK', { duration: 2500 });
      },
      error: () => this.snackBar.open('Bulk delete failed', 'OK', { duration: 3000 })
    });
  }
}

function compare(a: string | number, b: string | number, isAsc: boolean): number {
  return (a < b ? -1 : 1) * (isAsc ? 1 : -1);
}

/** Sort empty / null strings to the bottom regardless of asc/desc — useful
 * for Location and Source where a lot of rows can be blank and shouldn't
 * dominate either end of the order. */
function compareWithEmptyLast(a: string | null | undefined, b: string | null | undefined, isAsc: boolean): number {
  const x = (a || '').trim();
  const y = (b || '').trim();
  if (!x && !y) return 0;
  if (!x) return 1;
  if (!y) return -1;
  return x.localeCompare(y) * (isAsc ? 1 : -1);
}
