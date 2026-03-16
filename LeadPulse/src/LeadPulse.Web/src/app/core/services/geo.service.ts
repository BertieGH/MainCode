import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, catchError, shareReplay } from 'rxjs';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class GeoService {
  private countyCache: Record<string, Observable<string[]>> = {};
  private zipCache: Record<string, Observable<string[]>> = {};

  constructor(private http: HttpClient) {}

  /**
   * Get counties for a US state via backend (proxied Census API)
   */
  getCounties(stateCode: string): Observable<string[]> {
    if (!stateCode) return of([]);

    if (!this.countyCache[stateCode]) {
      this.countyCache[stateCode] = this.http.get<string[]>(
        `${environment.apiUrl}/geo/counties`,
        { params: { state: stateCode } }
      ).pipe(
        catchError(() => of([])),
        shareReplay(1)
      );
    }
    return this.countyCache[stateCode];
  }

  /**
   * Get zip codes for a county via backend (Census ZCTA relationship data)
   */
  getZipsForCounty(stateCode: string, countyName: string): Observable<string[]> {
    const cacheKey = `${stateCode}:${countyName}`;
    if (!this.zipCache[cacheKey]) {
      this.zipCache[cacheKey] = this.http.get<string[]>(
        `${environment.apiUrl}/geo/zips`,
        { params: { state: stateCode, county: countyName } }
      ).pipe(
        catchError(() => of([])),
        shareReplay(1)
      );
    }
    return this.zipCache[cacheKey];
  }
}
