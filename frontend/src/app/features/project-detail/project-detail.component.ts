import { DatePipe } from '@angular/common';
import { Component, DestroyRef, ViewChild, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { BreadcrumbComponent } from '../../core/components/breadcrumb/breadcrumb.component';
import { RunStatsChipsComponent } from '../../core/components/run-stats-chips/run-stats-chips.component';
import { SearchFieldComponent } from '../../core/components/search-field/search-field.component';
import { ProjectDetail, SuiteSummary } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

const VALID_STATUSES = ['pass', 'fail', 'new'] as const;
type Status = (typeof VALID_STATUSES)[number];

@Component({
  selector: 'app-project-detail',
  standalone: true,
  imports: [
    DatePipe,
    RouterLink,
    MatButtonModule,
    MatSortModule,
    MatTableModule,
    SearchFieldComponent,
    BreadcrumbComponent,
    RunStatsChipsComponent,
  ],
  templateUrl: './project-detail.component.html',
  styleUrl: './project-detail.component.scss',
})
export class ProjectDetailComponent {
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private destroyRef = inject(DestroyRef);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  private _sort: MatSort | undefined;

  private get sort(): MatSort | undefined {
    return this._sort;
  }

  @ViewChild(MatSort)
  private set sort(sort: MatSort | undefined) {
    if (!sort) return;
    this._sort = sort;
    this.dataSource.sort = sort;
    sort.sortChange.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((s: Sort) => {
      this.sortState.set(s);
      this.sortService.save('project-detail', s);
      this.writeQueryParams(
        s.active && s.direction ? { sort: s.active, dir: s.direction } : { sort: null, dir: null },
      );
    });
  }

  private readonly initialQueryParams = this.route.snapshot.queryParamMap;

  readonly columns = ['suite', 'latestRun', 'status'];
  readonly sortState = signal<Sort>(this.readInitialSort());
  readonly searchTerm = signal<string>(this.initialQueryParams.get('q') ?? '');
  readonly activeStatuses = signal<Set<Status>>(this.readInitialStatuses());
  readonly dataSource = new MatTableDataSource<SuiteSummary>();

  private readonly searchWrite$ = new Subject<string>();

  private readInitialSort(): Sort {
    const active = this.initialQueryParams.get('sort');
    if (active) {
      const dir = this.initialQueryParams.get('dir');
      return { active, direction: dir === 'desc' ? 'desc' : 'asc' };
    }
    return this.sortService.get('project-detail');
  }

  private readInitialStatuses(): Set<Status> {
    const raw = this.initialQueryParams.get('status');
    if (!raw) return new Set();
    return new Set(raw.split(',').filter((s): s is Status => VALID_STATUSES.includes(s as Status)));
  }

  private writeQueryParams(queryParams: Record<string, string | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  private params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });

  readonly projectSlug = computed(() => this.params().get('projectSlug') ?? '');

  private projectData = toSignal(
    this.route.paramMap.pipe(
      switchMap((p) =>
        this.api.projectDetail(p.get('projectSlug')!).pipe(catchError(() => of<ProjectDetail | null>(null))),
      ),
      takeUntilDestroyed(),
    ),
    { initialValue: undefined },
  );

  readonly loading = computed(() => this.projectData() === undefined);

  readonly project = computed(() => this.projectData() ?? null);

  readonly rows = computed<SuiteSummary[]>(() => this.project()?.suites ?? []);

  // A suite with no runs yet (`latest_run: null`) has no pass/fail/new signal
  // of its own. We classify it as "pass" for filtering purposes so it stays
  // neutral, mirroring the "all-zero totals -> pass" convention the main
  // projects list already uses for projects with no runs yet, rather than
  // inventing a fourth filter bucket or hiding the row entirely.
  private classifyRow(row: SuiteSummary): 'pass' | 'fail' | 'new' {
    const stats = row.latest_run;
    if (!stats) return 'pass';
    if (stats.unbaselined > 0) return 'new';
    if (stats.failing > 0) return 'fail';
    return 'pass';
  }

  readonly visibleRows = computed<SuiteSummary[]>(() => {
    const statuses = this.activeStatuses();
    if (statuses.size === 0) return this.rows();
    return this.rows().filter((row) => {
      const cls = this.classifyRow(row);
      return statuses.has(cls) || (cls === 'new' && statuses.has('fail'));
    });
  });

  constructor() {
    this.dataSource.filterPredicate = (row: SuiteSummary, filter: string) =>
      row.name.toLowerCase().includes(filter);

    this.dataSource.sortingDataAccessor = (row: SuiteSummary, sortHeaderId: string): string | number => {
      switch (sortHeaderId) {
        case 'suite':
          return row.name;
        case 'latestRun':
          return row.latest_run ? Date.parse(row.latest_run.created_at) : -1;
        default:
          return '';
      }
    };

    effect(() => {
      this.dataSource.data = this.visibleRows();
    });

    this.dataSource.filter = this.searchTerm().trim().toLowerCase();

    this.searchWrite$.pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef)).subscribe((value) => {
      this.writeQueryParams({ q: value.trim() || null });
    });
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
    this.dataSource.filter = value.trim().toLowerCase();
    this.searchWrite$.next(value);
  }

  toggleStatus(status: Status): void {
    this.activeStatuses.update((currentStatuses) => {
      const next = new Set(currentStatuses);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
      }
      return next;
    });
    const statuses = this.activeStatuses();
    this.writeQueryParams({ status: statuses.size > 0 ? Array.from(statuses).join(',') : null });
  }
}
