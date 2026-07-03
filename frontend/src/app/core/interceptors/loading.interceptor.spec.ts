import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { LoadingService } from '../services/loading.service';
import { loadingInterceptor } from './loading.interceptor';

describe('loadingInterceptor', () => {
  let http: HttpTestingController;
  let loadingSvc: LoadingService;
  let httpClient: HttpClient;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([loadingInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    loadingSvc = TestBed.inject(LoadingService);
    httpClient = TestBed.inject(HttpClient);
  });

  afterEach(() => http.verify());

  it('sets loading to true when request is in flight', () => {
    httpClient.get('/test').subscribe();
    expect(loadingSvc.loading()).toBe(true);
    http.expectOne('/test').flush({});
  });

  it('sets loading to false when request completes', () => {
    httpClient.get('/test').subscribe();
    http.expectOne('/test').flush({});
    expect(loadingSvc.loading()).toBe(false);
  });

  it('sets loading to false when request errors', () => {
    // eslint-disable-next-line @typescript-eslint/no-empty-function
    httpClient.get('/test').subscribe({ error: () => {} });
    http.expectOne('/test').flush('error', { status: 500, statusText: 'Server Error' });
    expect(loadingSvc.loading()).toBe(false);
  });
});
