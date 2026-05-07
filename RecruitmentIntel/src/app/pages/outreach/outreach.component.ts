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
import { downloadCsv } from '../../utils/csv-export';
import { ResizableColumnDirective } from '../../directives/resizable-column.directive';
import { ColumnWidthsService } from '../../services/column-widths.service';

@Component({
  selector: 'app-outreach',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatCardModule, MatTableModule, MatSelectModule, MatFormFieldModule,
    MatInputModule, MatButtonModule, MatIconModule, MatChipsModule, MatSortModule,
    MatTooltipModule, MatDialogModule, MatSnackBarModule,
    ResizableColumnDirective
  ],
  templateUrl: './outreach.component.html',
  styleUrl: './outreach.component.scss'
})
export class OutreachComponent implements OnInit {
  jobs: Job[] = [];
  lists: ProspectList[] = [];
  displayedColumns = ['companyName', 'title', 'matchTarget', 'department', 'seniority', 'jobType', 'location', 'skills', 'website', 'linkedin', 'link'];

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

  columnWidths: Record<string, number> = {};

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar,
    private dialog: MatDialog,
    private widthsSvc: ColumnWidthsService,
  ) {
    this.columnWidths = this.widthsSvc.load('outreach');
  }

  onColumnResized(col: string, w: number) {
    this.columnWidths = { ...this.columnWidths, [col]: w };
    this.widthsSvc.save('outreach', this.columnWidths);
  }

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
    if (!sort.active || sort.direction === '') return;
    const isAsc = sort.direction === 'asc';
    const cmpStr = (a: string, b: string) => {
      const sa = (a || '').toLowerCase();
      const sb = (b || '').toLowerCase();
      // Empty values sort last regardless of direction so blank rows
      // don't push useful data off the visible page.
      if (!sa && sb) return 1;
      if (sa && !sb) return -1;
      return sa < sb ? (isAsc ? -1 : 1) : sa > sb ? (isAsc ? 1 : -1) : 0;
    };
    const data = [...this.jobs];
    this.jobs = data.sort((a, b) => {
      switch (sort.active) {
        case 'companyName': return cmpStr(a.companyName, b.companyName);
        case 'title':       return cmpStr(a.title, b.title);
        case 'matchTarget': return cmpStr(a.matchTarget || '', b.matchTarget || '');
        case 'department':  return cmpStr(a.department, b.department);
        case 'seniority':   return cmpStr(a.seniority, b.seniority);
        case 'jobType':     return cmpStr(a.jobType, b.jobType);
        case 'location':    return cmpStr(a.location, b.location);
        default: return 0;
      }
    });
  }

  exportCsv() {
    const listName = this.lists.find(l => l.id === this.selectedList)?.name || 'outreach';
    const slug = listName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    downloadCsv(`outreach-${slug}`, [
      { header: 'Company', value: j => j.companyName },
      { header: 'Title', value: j => j.title },
      { header: 'Match Target', value: j => j.matchTarget },
      { header: 'Department', value: j => j.department },
      { header: 'Seniority', value: j => j.seniority },
      { header: 'Job Type', value: j => j.jobType },
      { header: 'Location', value: j => j.location },
      { header: 'Skills', value: j => j.skills },
      { header: 'Website', value: j => j.website },
      { header: 'LinkedIn', value: j => j.linkedinUrl },
      { header: 'URL', value: j => j.url },
      { header: 'Discovered', value: j => j.discoveredAt },
    ], this.jobs);
  }
}
