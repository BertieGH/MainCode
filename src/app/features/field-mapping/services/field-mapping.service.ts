import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  FieldMapping,
  CreateFieldMapping,
  UpdateFieldMapping,
  TestMapping,
  TestMappingResult
} from '../../../core/models/field-mapping.model';
import { environment } from '../../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class FieldMappingService {
  private readonly apiUrl = `${environment.apiUrl}/fieldmappings`;

  constructor(private http: HttpClient) {}

  /**
   * Get all field mappings
   */
  getAllMappings(): Observable<FieldMapping[]> {
    return this.http.get<FieldMapping[]>(this.apiUrl);
  }

  /**
   * Get field mapping by ID
   */
  getMappingById(id: number): Observable<FieldMapping> {
    return this.http.get<FieldMapping>(`${this.apiUrl}/${id}`);
  }

  /**
   * Create new field mapping
   */
  createMapping(mapping: CreateFieldMapping): Observable<FieldMapping> {
    return this.http.post<FieldMapping>(this.apiUrl, mapping);
  }

  /**
   * Update field mapping
   */
  updateMapping(id: number, mapping: UpdateFieldMapping): Observable<FieldMapping> {
    return this.http.put<FieldMapping>(`${this.apiUrl}/${id}`, mapping);
  }

  /**
   * Delete field mapping
   */
  deleteMapping(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }

  /**
   * Test mappings with sample data
   */
  testMappings(testData: TestMapping): Observable<TestMappingResult> {
    return this.http.post<TestMappingResult>(`${this.apiUrl}/test`, testData);
  }
}
