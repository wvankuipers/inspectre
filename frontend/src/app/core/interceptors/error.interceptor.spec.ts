import {
  HttpClient,
  HttpErrorResponse,
  HttpRequest,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { errorInterceptor } from './error.interceptor';

describe('errorInterceptor', () => {
  let http: HttpTestingController;
  let httpClient: HttpClient;
  let snackBarOpen: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    snackBarOpen = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        { provide: MatSnackBar, useValue: { open: snackBarOpen } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    httpClient = TestBed.inject(HttpClient);
  });

  afterEach(() => http.verify());

  it('shows network error message when status is 0', () => {
    // eslint-disable-next-line @typescript-eslint/no-empty-function
    httpClient.get('/test').subscribe({ error: () => {} });
    http.expectOne('/test').flush('network error', { status: 0, statusText: '' });
    expect(snackBarOpen).toHaveBeenCalledWith(
      'Cannot reach Inspectre. Check your connection.',
      'Dismiss',
      expect.objectContaining({ duration: 5000 }),
    );
  });

  it('shows 404 Not Found message for HTTP 404', () => {
    // eslint-disable-next-line @typescript-eslint/no-empty-function
    httpClient.get('/test').subscribe({ error: () => {} });
    http.expectOne('/test').flush('not found', { status: 404, statusText: 'Not Found' });
    expect(snackBarOpen).toHaveBeenCalledWith(
      '404 Not Found',
      'Dismiss',
      expect.objectContaining({ duration: 5000 }),
    );
  });

  it('falls back to "error" when statusText is empty for HTTP 500', () => {
    // HttpErrorResponse always normalises empty statusText to 'Unknown Error' in its constructor.
    // To reach the || 'error' branch in the interceptor, we call the interceptor function directly
    // with a plain object that mimics HttpErrorResponse but has statusText set to ''.
    const req = new HttpRequest('GET', '/test');
    const mockError = { status: 500, statusText: '' } as HttpErrorResponse;
    const next = () => throwError(() => mockError);

    TestBed.runInInjectionContext(() => {
      errorInterceptor(req, next as never).subscribe({ error: vi.fn() });
    });

    expect(snackBarOpen).toHaveBeenCalledWith(
      '500 error',
      'Dismiss',
      expect.objectContaining({ duration: 5000 }),
    );
  });

  it('re-throws the error so subscribers receive it', () => {
    const errorSpy = vi.fn();
    httpClient.get('/test').subscribe({ error: errorSpy });
    http.expectOne('/test').flush('server error', { status: 500, statusText: 'Server Error' });
    expect(errorSpy).toHaveBeenCalled();
  });

  it('does not call snackBar.open on successful requests', () => {
    httpClient.get('/test').subscribe();
    http.expectOne('/test').flush({ ok: true });
    expect(snackBarOpen).not.toHaveBeenCalled();
  });
});
