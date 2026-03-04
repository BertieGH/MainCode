import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { FieldMapping } from '../../../../core/models/field-mapping.model';
import { FieldMappingService } from '../../services/field-mapping.service';
import { MappingFormComponent } from '../mapping-form/mapping-form.component';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-mapping-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatProgressSpinnerModule,
    MatDialogModule
  ],
  templateUrl: './mapping-list.component.html',
  styleUrls: ['./mapping-list.component.scss']
})
export class MappingListComponent implements OnInit {
  mappings: FieldMapping[] = [];
  loading = true;
  error = '';

  displayedColumns = ['crmFieldName', 'surveyFieldName', 'fieldType', 'isRequired', 'actions'];

  constructor(
    private fieldMappingService: FieldMappingService,
    private router: Router,
    private dialog: MatDialog,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.pageTitle.setTitle('CRM Mappings', 'Manage field mappings between CRM and surveys');
    this.loadMappings();
  }

  loadMappings(): void {
    this.loading = true;
    this.fieldMappingService.getAllMappings().subscribe({
      next: (data) => {
        this.mappings = data;
        this.loading = false;
      },
      error: (err) => {
        this.error = 'Failed to load field mappings';
        this.loading = false;
        console.error('Error loading mappings:', err);
      }
    });
  }

  openCreateDialog(): void {
    const dialogRef = this.dialog.open(MappingFormComponent, {
      width: '600px',
      data: { mode: 'create' }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.loadMappings();
      }
    });
  }

  openEditDialog(mapping: FieldMapping): void {
    const dialogRef = this.dialog.open(MappingFormComponent, {
      width: '600px',
      data: { mode: 'edit', mapping }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.loadMappings();
      }
    });
  }

  deleteMapping(mapping: FieldMapping): void {
    if (confirm(`Are you sure you want to delete the mapping "${mapping.crmFieldName}"?`)) {
      this.fieldMappingService.deleteMapping(mapping.id).subscribe({
        next: () => {
          this.loadMappings();
        },
        error: (err) => {
          console.error('Error deleting mapping:', err);
          alert('Failed to delete mapping');
        }
      });
    }
  }

  navigateToTest(): void {
    this.router.navigate(['/field-mapping/test']);
  }
}
