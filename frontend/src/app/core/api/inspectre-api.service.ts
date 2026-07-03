import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Baseline, Project, RunDetail, SuiteDetail } from '../models/api';

@Injectable({ providedIn: 'root' })
export class InspectreApiService {
  private http = inject(HttpClient);

  // Same-origin in production (relative paths Just Work). For split-host
  // topology, set this to the API origin via an environment file; do not bake
  // host names into route components.
  private readonly apiBase = '/api';

  // ---- Read paths --------------------------------------------------------

  projects(): Observable<Project[]> {
    return this.http.get<Project[]>(`${this.apiBase}/projects/`);
  }

  suite(projectSlug: string, suiteSlug: string): Observable<SuiteDetail> {
    return this.http.get<SuiteDetail>(
      `${this.apiBase}/projects/${encodeURIComponent(projectSlug)}/suites/${encodeURIComponent(suiteSlug)}/`
    );
  }

  run(projectSlug: string, suiteSlug: string, seqId: number): Observable<RunDetail> {
    return this.http.get<RunDetail>(
      `${this.apiBase}/projects/${encodeURIComponent(projectSlug)}/suites/${encodeURIComponent(suiteSlug)}/runs/${seqId}/`,
    );
  }

  baseline(key: string): Observable<Baseline> {
    return this.http.get<Baseline>(`${this.apiBase}/baselines/${encodeURIComponent(key)}/`);
  }

  // ---- Mutations ---------------------------------------------------------

  setBaseline(testId: number): Observable<void> {
    // Empty body, JSON content-type. Server ignores the body and always promotes
    // (test_spa_api.py::TestSetBaselineSpa::test_body_content_is_ignored pins this).
    return this.http.post<void>(`${this.apiBase}/tests/${testId}/set-baseline/`, {});
  }
}
