import { TestBed } from '@angular/core/testing';
import { describe, it, expect, beforeEach } from 'vitest';
import { LoadingService } from './loading.service';

describe('LoadingService', () => {
  let svc: LoadingService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    svc = TestBed.inject(LoadingService);
  });

  it('loading is false when count is 0', () => {
    expect(svc.loading()).toBe(false);
  });

  it('loading is true after increment()', () => {
    svc.increment();
    expect(svc.loading()).toBe(true);
  });

  it('loading returns to false after matching decrement()', () => {
    svc.increment();
    svc.decrement();
    expect(svc.loading()).toBe(false);
  });

  it('decrement() does not go below 0', () => {
    svc.decrement();
    expect(svc.loading()).toBe(false);
    svc.increment();
    expect(svc.loading()).toBe(true);
  });
});
