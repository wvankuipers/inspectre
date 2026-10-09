import { Component, Type, input } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { appConfig } from './app.config';
import { InspectreApiService } from './core/api/inspectre-api.service';
import { ProjectDetailComponent } from './features/project-detail/project-detail.component';
import { RunDetailComponent } from './features/run-detail/run-detail.component';
import { SuiteDetailComponent } from './features/suite-detail/suite-detail.component';
import { TestDetailComponent } from './features/test-detail/test-detail.component';

@Component({ selector: 'app-query-host', template: '' })
class QueryHostComponent {
  readonly q = input('default');
}

// The real routes render pages inside AppShellComponent, so look the page up in the tree.
async function navigateTo<T>(url: string, type: Type<T>): Promise<T> {
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  await harness.fixture.whenStable();
  return harness.routeDebugElement!.query(By.directive(type)).componentInstance as T;
}

describe('router input binding (real appConfig and routes)', () => {
  const api = {
    projectDetail: vi.fn(),
    suite: vi.fn(),
    run: vi.fn(),
    testHistory: vi.fn(),
  };

  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset().mockReturnValue(throwError(() => new Error('mock'))));
    TestBed.configureTestingModule({
      providers: [...appConfig.providers, { provide: InspectreApiService, useValue: api }],
    });
  });

  afterEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
  });

  it('does not bind query params to inputs (guards queryParams: false in appConfig)', async () => {
    TestBed.inject(Router).resetConfig([{ path: 'x', component: QueryHostComponent }]);
    const harness = await RouterTestingHarness.create();
    const cmp = await harness.navigateByUrl('/x?q=1', QueryHostComponent);
    // Unbound inputs are reset to undefined by the router; with queryParams enabled this would be '1'.
    expect(cmp.q()).not.toBe('1');
  });

  it('binds project path params on the project route', async () => {
    const cmp = await navigateTo('/projects/p1', ProjectDetailComponent);
    expect(cmp.projectSlug()).toBe('p1');
    expect(api.projectDetail).toHaveBeenCalledWith('p1');
    expect(api.projectDetail).toHaveBeenCalledTimes(1);
  });

  it('binds project and suite path params on the suite route', async () => {
    const cmp = await navigateTo('/projects/p1/suites/s1', SuiteDetailComponent);
    expect(cmp.projectSlug()).toBe('p1');
    expect(cmp.suiteSlug()).toBe('s1');
    expect(api.suite).toHaveBeenCalledWith('p1', 's1');
    expect(api.suite).toHaveBeenCalledTimes(1);
  });

  it('binds slugs and a numeric seqId on the run route', async () => {
    const cmp = await navigateTo('/projects/p1/suites/s1/runs/7', RunDetailComponent);
    expect(cmp.projectSlug()).toBe('p1');
    expect(cmp.suiteSlug()).toBe('s1');
    expect(cmp.seqId()).toBe(7);
    expect(api.run).toHaveBeenCalledWith('p1', 's1', 7);
    expect(api.run).toHaveBeenCalledTimes(1);
  });

  it('binds slugs and key on the test route', async () => {
    const cmp = await navigateTo('/projects/p1/suites/s1/tests/k1', TestDetailComponent);
    expect(cmp.projectSlug()).toBe('p1');
    expect(cmp.suiteSlug()).toBe('s1');
    expect(cmp.key()).toBe('k1');
    expect(api.testHistory).toHaveBeenCalledWith('p1', 's1', 'k1');
    expect(api.testHistory).toHaveBeenCalledTimes(1);
  });

  it('takes the load-error path for a non-numeric run id', async () => {
    const cmp = await navigateTo('/projects/p/suites/s/runs/abc', RunDetailComponent);
    // numberAttribute's fallback is NaN (not 0), exactly what Number('abc') gave before.
    expect(cmp.seqId()).toBeNaN();
    expect(api.run).toHaveBeenCalledWith('p', 's', NaN);
    expect(cmp.loadError()).toBe(true);
  });
});
