import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { rxResource, takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
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
import { Baseline, RunSummary, SuiteDetail } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

@Component({
  selector: 'app-suite-detail',
  standalone: true,
  imports: [
    DatePipe,
    RouterLink,
    MatSortModule,
    MatTableModule,
    SearchFieldComponent,
    BreadcrumbComponent,
    RunStatsChipsComponent,
    MatTabsModule,
  ],
  templateUrl: './suite-detail.component.html',
  styleUrl: './suite-detail.component.scss',
})
export class SuiteDetailComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private destroyRef = inject(DestroyRef);

  readonly baselinesSort = viewChild<MatSort>('baselinesSort');

  readonly runColumns = ['seq', 'when', 'status'];
  readonly baselineColumns = ['name', 'browser', 'size', 'thumb'];

  private readonly initialQueryParams = this.route.snapshot.queryParamMap;

  readonly runSortState = signal<Sort>(
    this.readInitialSort('runsSort', 'runsDir', 'suite-runs', {
      active: 'seq',
      direction: 'desc',
    }),
  );

  readonly baselineSortState = signal<Sort>(
    this.readInitialSort('baselinesSort', 'baselinesDir', 'suite-baselines', {
      active: 'name',
      direction: 'asc',
    }),
  );

  readonly baselinesSearchTerm = signal<string>(this.initialQueryParams.get('baselinesQ') ?? '');
  readonly baselinesDataSource = new MatTableDataSource<Baseline>();

  private readonly baselinesSearchWrite$ = new Subject<string>();

  private readInitialSort(
    sortParam: string,
    dirParam: string,
    sortServiceKey: string,
    fallback: Sort,
  ): Sort {
    const active = this.initialQueryParams.get(sortParam);
    if (active) {
      const dir = this.initialQueryParams.get(dirParam);
      return { active, direction: dir === 'desc' ? 'desc' : 'asc' };
    }
    const saved = this.sortService.get(sortServiceKey);
    return saved.active ? saved : fallback;
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
  readonly suiteSlug = computed(() => this.params().get('suiteSlug') ?? '');

  private readonly chipLinks = new ChipLinkCache();

  chipLinkFor(run: RunSummary): ChipLinkFn {
    return this.chipLinks.get([
      '/projects',
      this.projectSlug(),
      'suites',
      this.suiteSlug(),
      'runs',
      run.sequential_id,
    ]);
  }

  private readonly suiteResource = rxResource({
    params: () => ({ project: this.projectSlug(), suite: this.suiteSlug() }),
    stream: ({ params }) => this.api.suite(params.project, params.suite),
  });

  readonly suite = computed<SuiteDetail | null>(() =>
    this.suiteResource.hasValue() ? this.suiteResource.value() : null,
  );

  readonly sortedRuns = computed<RunSummary[]>(() => {
    const { active, direction } = this.runSortState();
    const data = [...(this.suite()?.latest_runs ?? [])];
    if (!active || !direction) return data;
    return data.sort((a, b) => {
      const directionMultiplier = direction === 'asc' ? 1 : -1;
      switch (active) {
        case 'seq':
          return directionMultiplier * (a.sequential_id - b.sequential_id);
        case 'when':
          return directionMultiplier * (Date.parse(a.created_at) - Date.parse(b.created_at));
        default:
          return 0;
      }
    });
  });

  constructor() {
    this.baselinesDataSource.filterPredicate = (baseline: Baseline, filter: string) =>
      baseline.name.toLowerCase().includes(filter);

    effect((onCleanup) => {
      const sort = this.baselinesSort();
      if (!sort) return;
      this.baselinesDataSource.sort = sort;
      const sub = sort.sortChange.subscribe((s: Sort) => {
        this.baselineSortState.set(s);
        this.sortService.save('suite-baselines', s);
        this.writeQueryParams(
          s.active && s.direction
            ? { baselinesSort: s.active, baselinesDir: s.direction }
            : { baselinesSort: null, baselinesDir: null },
        );
      });
      onCleanup(() => sub.unsubscribe());
    });

    effect(() => {
      this.baselinesDataSource.data = this.suite()?.baselines ?? [];
    });

    this.baselinesDataSource.filter = this.baselinesSearchTerm().trim().toLowerCase();

    this.baselinesSearchWrite$
      .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => {
        this.writeQueryParams({ baselinesQ: value.trim() || null });
      });
  }

  onRunSortChange(sort: Sort): void {
    this.runSortState.set(sort);
    this.sortService.save('suite-runs', sort);
    this.writeQueryParams(
      sort.active && sort.direction
        ? { runsSort: sort.active, runsDir: sort.direction }
        : { runsSort: null, runsDir: null },
    );
  }

  onBaselinesSearch(value: string): void {
    this.baselinesSearchTerm.set(value);
    this.baselinesDataSource.filter = value.trim().toLowerCase();
    this.baselinesSearchWrite$.next(value);
  }
}
