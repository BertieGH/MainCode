import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Tenant, CreateTenantRequest, SubscriptionPlan, ImpersonateResponse } from '../models/tenant.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class TenantService {
  private url = `${environment.apiUrl}/tenants`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Tenant[]> {
    return this.http.get<Tenant[]>(this.url);
  }

  getById(id: number): Observable<Tenant> {
    return this.http.get<Tenant>(`${this.url}/${id}`);
  }

  create(req: CreateTenantRequest): Observable<Tenant> {
    return this.http.post<Tenant>(this.url, req);
  }

  updatePlan(id: number, planId: number): Observable<any> {
    return this.http.put(`${this.url}/${id}/plan`, { planId });
  }

  suspend(id: number): Observable<any> {
    return this.http.put(`${this.url}/${id}/suspend`, {});
  }

  reactivate(id: number): Observable<any> {
    return this.http.put(`${this.url}/${id}/reactivate`, {});
  }

  delete(id: number): Observable<any> {
    return this.http.delete(`${this.url}/${id}`);
  }

  impersonate(id: number): Observable<ImpersonateResponse> {
    return this.http.post<ImpersonateResponse>(`${this.url}/${id}/impersonate`, {});
  }

  migrateAll(): Observable<any> {
    return this.http.post(`${this.url}/migrate-all`, {});
  }

  getPlans(): Observable<SubscriptionPlan[]> {
    return this.http.get<SubscriptionPlan[]>(`${this.url}/plans`);
  }
}
