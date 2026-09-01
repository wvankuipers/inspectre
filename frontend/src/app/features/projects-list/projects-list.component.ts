import { DatePipe } from '@angular/common';
import {
  Component,
  DestroyRef,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, catchError, debounceTime, of } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { RunStatsChipsComponent } from '../../core/components/run-stats-chips/run-stats-chips.component';
import { SearchFieldComponent } from '../../core/components/search-field/search-field.component';
import { Project, SuiteSummary } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

interface Row {
  project: Project;
  suite: SuiteSummary;
}

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
      this.sortService.save('projects', s);
      this.writeQueryParams(
        s.active && s.direction ? { sort: s.active, dir: s.direction } : { sort: null, dir: null },
      );
    });
  }

  private readonly initialQueryParams = this.route.snapshot.queryParamMap;

  readonly columns = ['project', 'suite', 'latestRun', 'status'];
  readonly sortState = signal<Sort>(this.readInitialSort());
  readonly searchTerm = signal<string>(this.initialQueryParams.get('q') ?? '');
  readonly activeStatuses = signal<Set<Status>>(this.readInitialStatuses());
  readonly dataSource = new MatTableDataSource<Row>();

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
      catchError(() => of<Project[]>([])),
    ),
    { initialValue: undefined },
  );

  readonly loading = computed(() => this.projects() === undefined);

  readonly rows = computed<Row[]>(() => {
    const projects = this.projects() ?? [];
    return projects.flatMap((project) => project.suites.map((suite) => ({ project, suite })));
  });

  private classifyRun(run: SuiteSummary['latest_run']): 'pass' | 'fail' | 'new' {
    if (!run) return 'pass';
    if (run.unbaselined > 0) return 'new';
    if (run.failing > 0) return 'fail';
    return 'pass';
  }

  readonly visibleRows = computed<Row[]>(() => {
    const statuses = this.activeStatuses();
    if (statuses.size === 0) return this.rows();
    return this.rows().filter((row) => {
      const run = row.suite.latest_run;
      if (!run) return false;
      const cls = this.classifyRun(run);
      return statuses.has(cls) || (cls === 'new' && statuses.has('fail'));
    });
  });

  constructor() {
    this.dataSource.filterPredicate = (row: Row, filter: string) =>
      row.project.name.toLowerCase().includes(filter) ||
      row.suite.name.toLowerCase().includes(filter);

    this.dataSource.sortingDataAccessor = (row: Row, sortHeaderId: string): string | number => {
      switch (sortHeaderId) {
        case 'project':
          return row.project.name;
        case 'suite':
          return row.suite.name;
        case 'latestRun':
          return row.suite.latest_run ? Date.parse(row.suite.latest_run.created_at) : -1;
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
