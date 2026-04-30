import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { Job, ProspectList } from '../../models/interfaces';
import { ApiService } from '../../services/api.service';
import { InfoDialogComponent } from '../../components/info-dialog/info-dialog.component';
import { OUTREACH_WORKFLOW } from '../../components/info-dialog/workflows';

@Component({
  selector: 'app-outreach',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatTableModule, MatSelectModule, MatFormFieldModule,
    MatInputModule, MatButtonModule, MatIconModule, MatChipsModule, MatSortModule,
    MatTooltipModule, MatDialogModule, MatSnackBarModule
  ],
  templateUrl: './outreach.component.html',
  styleUrl: './outreach.component.scss'
})
export class OutreachComponent implements OnInit {
  jobs: Job[] = [];
  lists: ProspectList[] = [];
  displayedColumns = ['companyName', 'title', 'matchTarget', 'department', 'seniority', 'jobType', 'location', 'skills', 'link'];

  selectedList = '';
  filterDept = 'All';
  filterSeniority = 'All';
  filterJobType = 'All';
  filterLocation = '';
  filterSkills = '';

  departments = ['All', 'Engineering', 'Sales', 'Marketing', 'Product', 'People'];
  seniorities = ['All', 'Junior', 'Mid', 'Senior', 'Lead'];
  jobTypes = ['All', 'Full-time', 'Contract', 'Part-time'];

  // Client-side alias retained so the template doesn't need to change
  get filteredJobs(): Job[] { return this.jobs; }

  constructor(private api: ApiService, private snackBar: MatSnackBar, private dialog: MatDialog) {}

  openInfo() {
    this.dialog.open(InfoDialogComponent, { data: OUTREACH_WORKFLOW, width: '880px', maxWidth: '95vw' });
  }

  ngOnInit() {
    this.api.getProspectLists().subscribe({
      next: (data) => {
        this.lists = data;
        if (data.length && !this.selectedList) {
          this.selectedList = data[0].id;
          this.loadJobs();
        }
      },
      error: () => this.snackBar.open('Failed to load lists', 'OK', { duration: 3000 })
    });
  }

  get deptSummary(): { name: string; count: number }[] {
    const counts = new Map<string, number>();
    this.jobs.forEach(j => counts.set(j.department, (counts.get(j.department) || 0) + 1));
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }

  onListChange() {
    this.loadJobs();
  }

  loadJobs() {
    if (!this.selectedList) { this.jobs = []; return; }
    this.api.getOutreach(this.selectedList, this.buildFilters()).subscribe({
      next: (data) => this.jobs = data,
      error: () => this.snackBar.open('Failed to load jobs', 'OK', { duration: 3000 })
    });
  }

  private buildFilters() {
    const f: any = {};
    if (this.filterDept !== 'All') f.department = this.filterDept;
    if (this.filterSeniority !== 'All') f.seniority = this.filterSeniority;
    if (this.filterJobType !== 'All') f.job_type = this.filterJobType;
    if (this.filterLocation) f.location = this.filterLocation;
    if (this.filterSkills) f.skills = this.filterSkills;
    return f;
  }

  applyFilters() {
    this.loadJobs();
  }

  clearFilters() {
    this.filterDept = 'All';
    this.filterSeniority = 'All';
    this.filterJobType = 'All';
    this.filterLocation = '';
    this.filterSkills = '';
    this.loadJobs();
  }

  sortData(sort: Sort) {
    const data = [...this.jobs];
    if (!sort.active || sort.direction === '') return;
    this.jobs = data.sort((a, b) => {
      const isAsc = sort.direction === 'asc';
      switch (sort.active) {
        case 'companyName': return (a.companyName < b.companyName ? -1 : 1) * (isAsc ? 1 : -1);
        case 'title': return (a.title < b.title ? -1 : 1) * (isAsc ? 1 : -1);
        case 'department': return (a.department < b.department ? -1 : 1) * (isAsc ? 1 : -1);
        default: return 0;
      }
    });
  }

  exportCsv() {
    if (!this.selectedList) return;
    const url = this.api.exportOutreachCsv(this.selectedList, this.buildFilters());
    window.location.href = url;
  }
}
