import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { InspectreApiService } from './core/api/inspectre-api.service';
import { ProjectDetail } from './core/models/api';
import { ProjectDetailComponent } from './features/project-detail/project-detail.component';
import { RunDetailComponent } from './features/run-detail/run-detail.component';

const PROJECT: ProjectDetail = { id: 1, name: 'Real', slug: 'real', suites: [] };

describe('router input binding', () => {
  afterEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
  });

  it('binds path params to inputs and ignores same-named query params', async () => {
    const projectDetail = vi.fn(() => of(PROJECT));
    TestBed.configureTestingModule({
      providers: [
        provideRouter(
          [{ path: 'projects/:projectSlug', component: ProjectDetailComponent }],
          withComponentInputBinding({ queryParams: false }),
        ),
        { provide: InspectreApiService, useValue: { projectDetail } },
      ],
    });
    const harness = await RouterTestingHarness.create();
    const cmp = await harness.navigateByUrl(
      '/projects/real?projectSlug=evil',
      ProjectDetailComponent,
    );
    await harness.fixture.whenStable();
    expect(cmp.projectSlug()).toBe('real');
    expect(projectDetail).toHaveBeenCalledWith('real');
    expect(projectDetail).not.toHaveBeenCalledWith('evil');
  });

  it('takes the load-error path for a non-numeric run id', async () => {
    const run = vi.fn(() => throwError(() => new Error('404')));
    TestBed.configureTestingModule({
      providers: [
        provideRouter(
          [
            {
              path: 'projects/:projectSlug/suites/:suiteSlug/runs/:seqId',
              component: RunDetailComponent,
            },
          ],
          withComponentInputBinding({ queryParams: false }),
        ),
        { provide: InspectreApiService, useValue: { run } },
      ],
    });
    const harness = await RouterTestingHarness.create();
    const cmp = await harness.navigateByUrl('/projects/p/suites/s/runs/abc', RunDetailComponent);
    await harness.fixture.whenStable();
    // numberAttribute's fallback is NaN (not 0), exactly what Number('abc') gave before.
    expect(cmp.seqId()).toBeNaN();
    expect(run).toHaveBeenCalledWith('p', 's', NaN);
    expect(cmp.loadError()).toBe(true);
  });
});
