import { Component, Inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { FieldMapping, FIELD_TYPES } from '../../../../core/models/field-mapping.model';
import { FieldMappingService } from '../../services/field-mapping.service';

@Component({
  selector: 'app-mapping-form',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatButtonModule,
    MatIconModule
  ],
  templateUrl: './mapping-form.component.html',
  styleUrls: ['./mapping-form.component.scss']
})
export class MappingFormComponent implements OnInit {
  form: FormGroup;
  fieldTypes = FIELD_TYPES;
  mode: 'create' | 'edit' = 'create';
  mapping?: FieldMapping;
  submitting = false;
  error = '';

  constructor(
    private fb: FormBuilder,
    private fieldMappingService: FieldMappingService,
    private dialogRef: MatDialogRef<MappingFormComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { mode: 'create' | 'edit', mapping?: FieldMapping }
  ) {
    this.mode = data.mode;
    this.mapping = data.mapping;

    this.form = this.fb.group({
      crmFieldName: ['', [Validators.required, Validators.maxLength(100)]],
      surveyFieldName: ['', [Validators.required, Validators.maxLength(100)]],
      fieldType: ['string', Validators.required],
      isRequired: [false]
    });
  }

  ngOnInit(): void {
    if (this.mode === 'edit' && this.mapping) {
      this.form.patchValue({
        crmFieldName: this.mapping.crmFieldName,
        surveyFieldName: this.mapping.surveyFieldName,
        fieldType: this.mapping.fieldType,
        isRequired: this.mapping.isRequired
      });
    }
  }

  onSubmit(): void {
    if (this.form.invalid) {
      return;
    }

    this.submitting = true;
    this.error = '';

    const formValue = this.form.value;

    if (this.mode === 'create') {
      this.fieldMappingService.createMapping(formValue).subscribe({
        next: () => {
          this.dialogRef.close(true);
        },
        error: (err) => {
          this.error = 'Failed to create field mapping';
          this.submitting = false;
          console.error('Error creating mapping:', err);
        }
      });
    } else if (this.mode === 'edit' && this.mapping) {
      this.fieldMappingService.updateMapping(this.mapping.id, formValue).subscribe({
        next: () => {
          this.dialogRef.close(true);
        },
        error: (err) => {
          this.error = 'Failed to update field mapping';
          this.submitting = false;
          console.error('Error updating mapping:', err);
        }
      });
    }
  }

  onCancel(): void {
    this.dialogRef.close(false);
  }
}
