import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { rxResource, takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, debounceTime } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { BreadcrumbComponent } from '../../core/components/breadcrumb/breadcrumb.component';
import { ChipLinkCache } from '../../core/components/run-stats-chips/chip-link-cache';
import {
  ChipLinkFn,
  RunStatsChipsComponent,
} from '../../core/components/run-stats-chips/run-stats-chips.component';
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

  private readonly matSort = viewChild(MatSort);

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

  private readonly chipLinks = new ChipLinkCache();

  chipLinkFor(row: SuiteSummary): ChipLinkFn | undefined {
    const run = row.latest_run;
    if (!run) return undefined;
    return this.chipLinks.get(['/projects', this.projectSlug(), 'suites', row.slug, 'runs', run.sequential_id]);
  }

  private readonly projectResource = rxResource({
    params: () => this.projectSlug(),
    stream: ({ params }) => this.api.projectDetail(params),
  });

  readonly loading = computed(() => this.projectResource.isLoading());

  readonly project = computed<ProjectDetail | null>(() =>
    this.projectResource.hasValue() ? this.projectResource.value() : null,
  );

  readonly rows = computed<SuiteSummary[]>(() => this.project()?.suites ?? []);

  // Count-based matching: a suite can match several statuses at once (e.g.
  // passing and failing tests show under both Pass and Fail). Fail also
  // matches unbaselined suites. A suite with no runs yet (`latest_run: null`)
  // has no signal of its own and counts as "pass" so it stays neutral rather
  // than inventing a fourth bucket or hiding the row.
  private matches(row: SuiteSummary, status: Status): boolean {
    const stats = row.latest_run;
    if (!stats) return status === 'pass';
    switch (status) {
      case 'pass':
        return stats.passing > 0 || (stats.failing === 0 && stats.unbaselined === 0);
      case 'fail':
        return stats.failing > 0 || stats.unbaselined > 0;
      case 'new':
        return stats.unbaselined > 0;
      default:
        return false;
    }
  }

  readonly visibleRows = computed<SuiteSummary[]>(() => {
    const statuses = this.activeStatuses();
    if (statuses.size === 0) return this.rows();
    return this.rows().filter((row) => [...statuses].some((st) => this.matches(row, st)));
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

    effect((onCleanup) => {
      const sort = this.matSort();
      if (!sort) return;
      this.dataSource.sort = sort;
      const sub = sort.sortChange.subscribe((s: Sort) => {
        this.sortState.set(s);
        this.sortService.save('project-detail', s);
        this.writeQueryParams(
          s.active && s.direction ? { sort: s.active, dir: s.direction } : { sort: null, dir: null },
        );
      });
      onCleanup(() => sub.unsubscribe());
    });

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
