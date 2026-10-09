import { DatePipe } from '@angular/common';
import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, catchError, debounceTime, of } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { ChipLinkCache } from '../../core/components/run-stats-chips/chip-link-cache';
import { ChipLinkFn, RunStatsChipsComponent } from '../../core/components/run-stats-chips/run-stats-chips.component';
import { SearchFieldComponent } from '../../core/components/search-field/search-field.component';
import { ProjectSummary } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

const VALID_STATUSES = ['pass', 'fail', 'new'] as const;
type Status = (typeof VALID_STATUSES)[number];

@Component({
  selector: 'app-projects-list',
  standalone: true,
  imports: [
    DatePipe,
    RouterLink,
    MatButtonModule,
    MatSortModule,
    MatTableModule,
    SearchFieldComponent,
    RunStatsChipsComponent,
  ],
  templateUrl: './projects-list.component.html',
  styleUrl: './projects-list.component.scss',
})
export class ProjectsListComponent {
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private destroyRef = inject(DestroyRef);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  private readonly matSort = viewChild(MatSort);

  private readonly initialQueryParams = this.route.snapshot.queryParamMap;

  readonly columns = ['project', 'suiteCount', 'latestRun', 'status'];
  readonly sortState = signal<Sort>(this.readInitialSort());
  readonly searchTerm = signal<string>(this.initialQueryParams.get('q') ?? '');
  readonly activeStatuses = signal<Set<Status>>(this.readInitialStatuses());
  readonly dataSource = new MatTableDataSource<ProjectSummary>();

  private readonly chipLinks = new ChipLinkCache();

  chipLinkFor(row: ProjectSummary): ChipLinkFn {
    if (!row.single_suite_slug) return this.chipLinks.get(['/projects', row.slug], 'except-flaky');
    const suite = ['/projects', row.slug, 'suites', row.single_suite_slug];
    const seq = row.single_suite_latest_run_seq;
    return seq == null ? this.chipLinks.get(suite, 'none') : this.chipLinks.get([...suite, 'runs', seq]);
  }

  private readonly searchWrite$ = new Subject<string>();

  private readInitialSort(): Sort {
    const active = this.initialQueryParams.get('sort');
    if (active) {
      const dir = this.initialQueryParams.get('dir');
      return { active, direction: dir === 'desc' ? 'desc' : 'asc' };
    }
    return this.sortService.get('projects');
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

  private projects = toSignal(
    this.api.projects().pipe(
      takeUntilDestroyed(),
      catchError(() => of<ProjectSummary[]>([])),
    ),
    { initialValue: undefined },
  );

  readonly loading = computed(() => this.projects() === undefined);

  readonly rows = computed<ProjectSummary[]>(() => this.projects() ?? []);

  // Count-based matching: a row can match several statuses at once (e.g. a
  // row with passing and failing tests shows under both Pass and Fail). Fail
  // also matches unbaselined rows. A project with all-zero totals (no runs
  // yet) stays neutral and counts as pass.
  private matches(row: ProjectSummary, status: Status): boolean {
    const t = row.totals;
    switch (status) {
      case 'pass':
        return t.passing > 0 || (t.failing === 0 && t.unbaselined === 0);
      case 'fail':
        return t.failing > 0 || t.unbaselined > 0;
      case 'new':
        return t.unbaselined > 0;
      default:
        return false;
    }
  }

  readonly visibleRows = computed<ProjectSummary[]>(() => {
    const statuses = this.activeStatuses();
    if (statuses.size === 0) return this.rows();
    return this.rows().filter((row) => [...statuses].some((st) => this.matches(row, st)));
  });

  constructor() {
    this.dataSource.filterPredicate = (row: ProjectSummary, filter: string) =>
      row.name.toLowerCase().includes(filter);

    this.dataSource.sortingDataAccessor = (row: ProjectSummary, sortHeaderId: string): string | number => {
      switch (sortHeaderId) {
        case 'project':
          return row.name;
        case 'suiteCount':
          return row.suite_count;
        case 'latestRun':
          return row.last_run_at ? Date.parse(row.last_run_at) : -1;
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
        this.sortService.save('projects', s);
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
