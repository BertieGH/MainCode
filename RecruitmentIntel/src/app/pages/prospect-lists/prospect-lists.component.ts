import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { InfoDialogComponent } from '../../components/info-dialog/info-dialog.component';
import { PROSPECT_THEAMS_WORKFLOW } from '../../components/info-dialog/workflows';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-prospect-lists',
  standalone: true,
  imports: [
    CommonModule, RouterLink, FormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatDialogModule,
    MatFormFieldModule, MatInputModule, MatProgressBarModule,
    MatTooltipModule, MatSnackBarModule
  ],
  templateUrl: './prospect-lists.component.html',
  styleUrl: './prospect-lists.component.scss'
})
export class ProspectListsComponent implements OnInit {
  lists: ProspectList[] = [];
  showNewForm = false;
  newName = '';
  newDescription = '';

  constructor(private api: ApiService, private snackBar: MatSnackBar, private dialog: MatDialog) {}

  openInfo() {
    this.dialog.open(InfoDialogComponent, { data: PROSPECT_THEAMS_WORKFLOW, width: '880px', maxWidth: '95vw' });
  }

  ngOnInit() {
    this.loadLists();
  }

  loadLists() {
    this.api.getProspectLists().subscribe({
      next: (data) => this.lists = data,
      error: () => this.snackBar.open('Failed to load lists', 'OK', { duration: 3000 })
    });
  }

  createList() {
    if (!this.newName.trim()) return;
    this.api.createProspectList(this.newName, this.newDescription).subscribe({
      next: (list) => {
        this.lists.unshift(list);
        this.newName = '';
        this.newDescription = '';
        this.showNewForm = false;
      },
      error: () => this.snackBar.open('Failed to create list', 'OK', { duration: 3000 })
    });
  }

  deleteList(id: string) {
    this.api.deleteProspectList(id).subscribe({
      next: () => this.lists = this.lists.filter(l => l.id !== id),
      error: () => this.snackBar.open('Failed to delete list', 'OK', { duration: 3000 })
    });
  }

  getEnrichmentPercent(list: ProspectList): number {
    return list.companyCount > 0 ? (list.enrichedCount / list.companyCount) * 100 : 0;
  }

  getCrawlPercent(list: ProspectList): number {
    return list.companyCount > 0 ? (list.jobsCrawledCount / list.companyCount) * 100 : 0;
  }
}
