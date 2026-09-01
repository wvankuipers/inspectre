import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectChange, MatSelectModule } from '@angular/material/select';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { BreadcrumbComponent } from '../../core/components/breadcrumb/breadcrumb.component';
import {
  ImageSlot,
  ImageViewerComponent,
} from '../../core/components/image-viewer/image-viewer.component';
import { SearchFieldComponent } from '../../core/components/search-field/search-field.component';
import { RunDetail, TestRow } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

@Component({
  selector: 'app-run-detail',
  standalone: true,
  imports: [
    DatePipe,
    NgTemplateOutlet,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSortModule,
    MatTableModule,
    RouterLink,
    SearchFieldComponent,
    BreadcrumbComponent,
  ],
  templateUrl: './run-detail.component.html',
  styleUrl: './run-detail.component.scss',
})
export class RunDetailComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private dialog = inject(MatDialog);
  private destroyRef = inject(DestroyRef);

  readonly columns = ['name', 'baseline', 'screenshot', 'diff', 'result'];

  private readonly initialQueryParams = this.route.snapshot.queryParamMap;

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

  private readInitialSet(param: string): Set<string> {
    const raw = this.initialQueryParams.get(param);
    if (!raw) return new Set();
    return new Set(raw.split(',').filter(Boolean));
  }

  private writeQueryParams(queryParams: Record<string, string | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  readonly sortState = signal<Sort>(
    this.readInitialSort('sort', 'dir', 'run-tests', { active: 'name', direction: 'asc' }),
  );

  private readonly searchWrite$ = new Subject<string>();

  private params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });

  readonly projectSlug = computed(() => this.params().get('projectSlug') ?? '');
  readonly suiteSlug = computed(() => this.params().get('suiteSlug') ?? '');
  readonly seqId = computed(() => Number(this.params().get('seqId') ?? 0));

  readonly loadError = signal<boolean>(false);

  private runData = signal<RunDetail | undefined>(undefined);

  private mergeTests(updated: TestRow[]): void {
    if (updated.length === 0) return;
    const byId = new Map(updated.map((t) => [t.id, t]));
    this.runData.update((current) => {
      if (!current) return current;
      return {
        ...current,
        tests: current.tests.map((t) => byId.get(t.id) ?? t),
      };
    });
  }

  readonly thumbLoaded = signal<Set<string>>(new Set<string>());

  onImgLoad(src: string): void {
    this.thumbLoaded.update((previouslyLoaded) => new Set(previouslyLoaded).add(src));
  }

  readonly run = computed(() => this.runData() ?? null);

  readonly hasPendingTests = computed(() => {
    const runData = this.run();
    if (!runData) return false;
    return runData.tests.some((t) => t.status !== 'done' && t.status !== 'failed');
  });

  private pollTimer: ReturnType<typeof setTimeout> | undefined;

  // Consecutive polls where testsBulk returned none of the requested ids, or
  // errored outright. Caps runaway polling if the pending tests are never
  // going to resolve (e.g. their run was deleted by retention cleanup while
  // this page was open) — otherwise hasPendingTests() stays true forever and
  // the component polls every 10s indefinitely.
  private unproductivePollCount = 0;
  private static readonly MAX_UNPRODUCTIVE_POLLS = 3;

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((params) => {
          this.loadError.set(false);
          return this.api
            .run(params.get('projectSlug')!, params.get('suiteSlug')!, Number(params.get('seqId')))
            .pipe(
              catchError(() => {
                this.loadError.set(true);
                return of<RunDetail | null>(null);
              }),
            );
        }),
        takeUntilDestroyed(),
      )
      .subscribe((runData) => {
        this.runData.set(runData ?? undefined);
        this.unproductivePollCount = 0;
        this.schedulePollIfNeeded();
      });

    this.destroyRef.onDestroy(() => clearTimeout(this.pollTimer));

    this.searchWrite$
      .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => {
        this.writeQueryParams({ q: value.trim() || null });
      });
  }

  private schedulePollIfNeeded(): void {
    clearTimeout(this.pollTimer);
    if (!this.hasPendingTests()) return;
    this.pollTimer = setTimeout(() => this.pollPendingTests(), 10000);
  }

  private pollPendingTests(): void {
    const pendingIds = (this.run()?.tests ?? [])
      .filter((t) => t.status !== 'done' && t.status !== 'failed')
      .map((t) => t.id);
    if (pendingIds.length === 0) return;
    this.api
      .testsBulk(pendingIds)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          if (updated.length === 0) {
            this.registerUnproductivePoll();
            return;
          }
          this.unproductivePollCount = 0;
          this.mergeTests(updated);
          this.schedulePollIfNeeded();
        },
        error: () => this.registerUnproductivePoll(),
      });
  }

  private registerUnproductivePoll(): void {
    this.unproductivePollCount++;
    if (this.unproductivePollCount >= RunDetailComponent.MAX_UNPRODUCTIVE_POLLS) return;
    this.schedulePollIfNeeded();
  }

  readonly pendingId = signal<Set<number>>(new Set());
  readonly searchTerm = signal<string>(this.initialQueryParams.get('q') ?? '');
  readonly activeStatuses = signal<Set<'pass' | 'fail' | 'new'>>(
    this.readInitialSet('status') as Set<'pass' | 'fail' | 'new'>,
  );
  readonly activeBrowsers = signal<Set<string>>(this.readInitialSet('browser'));
  readonly activeSizes = signal<Set<string>>(this.readInitialSet('size'));

  readonly availableBrowsers = computed<string[]>(() =>
    Array.from(new Set((this.run()?.tests ?? []).map((t) => t.browser))).sort(),
  );

  readonly availableSizes = computed<string[]>(() =>
    Array.from(new Set((this.run()?.tests ?? []).map((t) => t.size))).sort(),
  );

  readonly activeStatusesList = computed<string[]>(() => Array.from(this.activeStatuses()));
  readonly activeBrowsersList = computed<string[]>(() => Array.from(this.activeBrowsers()));
  readonly activeSizesList = computed<string[]>(() => Array.from(this.activeSizes()));

  private classifyTest(testRow: TestRow): 'pass' | 'fail' | 'new' {
    if (!testRow.has_baseline) return 'new';
    return testRow.passed ? 'pass' : 'fail';
  }

  readonly sortedTests = computed<TestRow[]>(() => {
    const { active, direction } = this.sortState();
    const data = [...(this.run()?.tests ?? [])];
    if (!active || !direction) return data;
    return data.sort((a, b) => {
      const directionMultiplier = direction === 'asc' ? 1 : -1;
      switch (active) {
        case 'name':
          return directionMultiplier * a.name.localeCompare(b.name);
        case 'result':
          return directionMultiplier * ((b.passed ? 1 : 0) - (a.passed ? 1 : 0));
        default:
          return 0;
      }
    });
  });

  readonly visibleTests = computed<TestRow[]>(() => {
    const lowerSearchTerm = this.searchTerm().toLowerCase();
    const statuses = this.activeStatuses();
    const browsers = this.activeBrowsers();
    const sizes = this.activeSizes();
    return this.sortedTests()
      .filter((testRow) => testRow.name.toLowerCase().includes(lowerSearchTerm))
      .filter((testRow) => {
        if (statuses.size === 0) return true;
        const cls = this.classifyTest(testRow);
        return statuses.has(cls) || (cls === 'new' && statuses.has('fail'));
      })
      .filter((testRow) => browsers.size === 0 || browsers.has(testRow.browser))
      .filter((testRow) => sizes.size === 0 || sizes.has(testRow.size));
  });

  onSortChange(sort: Sort): void {
    this.sortState.set(sort);
    this.sortService.save('run-tests', sort);
    this.writeQueryParams(
      sort.active && sort.direction
        ? { sort: sort.active, dir: sort.direction }
        : { sort: null, dir: null },
    );
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
    this.searchWrite$.next(value);
  }

  onStatusSelectionChange(event: MatSelectChange): void {
    const values = event.value as ('pass' | 'fail' | 'new')[];
    this.activeStatuses.set(new Set(values));
    this.writeQueryParams({ status: values.length ? values.join(',') : null });
  }

  onBrowserSelectionChange(event: MatSelectChange): void {
    const values = event.value as string[];
    this.activeBrowsers.set(new Set(values));
    this.writeQueryParams({ browser: values.length ? values.join(',') : null });
  }

  onSizeSelectionChange(event: MatSelectChange): void {
    const values = event.value as string[];
    this.activeSizes.set(new Set(values));
    this.writeQueryParams({ size: values.length ? values.join(',') : null });
  }

  openViewer(test: TestRow, slot: ImageSlot): void {
    const tests = this.visibleTests();
    const index = tests.indexOf(test);
    this.dialog.open(ImageViewerComponent, {
      data: { tests, index, slot },
      maxWidth: '100vw',
      maxHeight: '100vh',
      width: '100vw',
      height: '100vh',
      panelClass: 'image-viewer-panel',
    });
  }

  rebaseline(test: TestRow): void {
    this.pendingId.update((currentStatuses) => new Set(currentStatuses).add(test.id));
    this.api
      .setBaseline(test.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.pendingId.update((currentStatuses) => {
            const next = new Set(currentStatuses);
            next.delete(test.id);
            return next;
          });
          this.api
            .testsBulk([test.id])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (updated) => {
                this.mergeTests(updated);
                this.schedulePollIfNeeded();
              },
              error: () => this.schedulePollIfNeeded(),
            });
        },
        error: () => {
          this.pendingId.update((currentStatuses) => {
            const next = new Set(currentStatuses);
            next.delete(test.id);
            return next;
          });
        },
      });
  }

  trackByTestId(_index: number, test: TestRow): number {
    return test.id;
  }

  onImgError(event: Event): void {
    const img = event.target as HTMLImageElement;
    if (img.dataset['failed']) return;
    img.dataset['failed'] = '1';
    img.src = '/image_not_found.jpg';
  }
}
