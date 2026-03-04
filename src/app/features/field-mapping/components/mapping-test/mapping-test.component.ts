import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Router } from '@angular/router';
import { FieldMappingService } from '../../services/field-mapping.service';
import { TestMappingResult } from '../../../../core/models/field-mapping.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-mapping-test',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './mapping-test.component.html',
  styleUrls: ['./mapping-test.component.scss']
})
export class MappingTestComponent implements OnInit {
  form: FormGroup;
  testResult: TestMappingResult | null = null;
  testing = false;
  error = '';

  sampleFields = [
    { key: 'Clients.Id', value: 'CRM001', description: 'Client ID from CRM' },
    { key: 'Clients.Name', value: 'John Doe', description: 'Client full name' },
    { key: 'Clients.Email', value: 'john.doe@example.com', description: 'Client email' },
    { key: 'Clients.Phone', value: '555-1234', description: 'Client phone' },
    { key: 'Clients.CompanyName', value: 'Acme Corp', description: 'Company name' }
  ];

  constructor(
    private fb: FormBuilder,
    private fieldMappingService: FieldMappingService,
    private router: Router,
    private pageTitle: PageTitleService
  ) {
    this.form = this.fb.group({});
  }

  ngOnInit(): void {
    this.pageTitle.setTitle('Test Mappings', 'Test your CRM field mappings');
    // Create form controls for sample fields
    this.sampleFields.forEach(field => {
      this.form.addControl(field.key, this.fb.control(field.value));
    });
  }

  testMappings(): void {
    this.testing = true;
    this.error = '';
    this.testResult = null;

    const sampleData: { [key: string]: string } = {};
    Object.keys(this.form.value).forEach(key => {
      const value = this.form.value[key];
      if (value && value.trim()) {
        sampleData[key] = value;
      }
    });

    this.fieldMappingService.testMappings({ sampleData }).subscribe({
      next: (result) => {
        this.testResult = result;
        this.testing = false;
      },
      error: (err) => {
        this.error = 'Failed to test mappings';
        this.testing = false;
        console.error('Error testing mappings:', err);
      }
    });
  }

  loadDefaults(): void {
    this.sampleFields.forEach(field => {
      this.form.get(field.key)?.setValue(field.value);
    });
  }

  clearAll(): void {
    this.form.reset();
    this.testResult = null;
  }

  goBack(): void {
    this.router.navigate(['/field-mapping']);
  }

  objectKeys(obj: { [key: string]: any }): string[] {
    return Object.keys(obj);
  }
}
