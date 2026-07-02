import { DatePipe, NgTemplateOutlet } from '@angular/common';
import {
  AfterViewInit,
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
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { ActivatedRoute } from '@angular/router';
import { BehaviorSubject, catchError, combineLatest, of, switchMap } from 'rxjs';

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
    MatSortModule,
    MatTableModule,
    SearchFieldComponent,
    BreadcrumbComponent,
  ],
  templateUrl: './run-detail.component.html',
  styleUrl: './run-detail.component.scss',
})
export class RunDetailComponent implements AfterViewInit {
  private route = inject(ActivatedRoute);
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private dialog = inject(MatDialog);
  private destroyRef = inject(DestroyRef);

  @ViewChild(MatSort) private sort!: MatSort;

  readonly columns = ['name', 'baseline', 'screenshot', 'diff', 'result'];

  readonly sortState = signal<Sort>(
    (() => {
      const saved = this.sortService.get('run-tests');
      return saved.active ? saved : { active: 'name', direction: 'asc' };
    })(),
  );

  private params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });

  readonly projectSlug = computed(() => this.params().get('projectSlug') ?? '');
  readonly suiteSlug = computed(() => this.params().get('suiteSlug') ?? '');
  readonly seqId = computed(() => Number(this.params().get('seqId') ?? 0));

  private reloadTrigger$ = new BehaviorSubject<void>(undefined);

  readonly loadError = signal<boolean>(false);

  private runData = toSignal(
    combineLatest([this.route.paramMap, this.reloadTrigger$]).pipe(
      switchMap(([params]) => {
        this.loadError.set(false);
        return this.api
          .run(params.get('projectSlug')!, params.get('suiteSlug')!, Number(params.get('seqId')))
          .pipe(catchError(() => { this.loadError.set(true); return of<RunDetail | null>(null); }));
      }),
      takeUntilDestroyed(),
    ),
    { initialValue: undefined },
  );

  private promotedIds = signal<Set<number>>(new Set());

  readonly thumbLoaded = signal<Set<string>>(new Set<string>());

  onImgLoad(src: string): void {
    this.thumbLoaded.update(previouslyLoaded => new Set(previouslyLoaded).add(src));
  }

  readonly run = computed(() => {
    const runData = this.runData() ?? null;
    if (!runData) return null;
    const promoted = this.promotedIds();
    if (promoted.size === 0) return runData;
    return {
      ...runData,
      tests: runData.tests.map((test) =>
        promoted.has(test.id) ? { ...test, passed: true } : test,
      ),
    };
  });

  readonly hasPendingTests = computed(() => {
    const runData = this.run();
    if (!runData) return false;
    return runData.tests.some((t) => t.status !== 'done' && t.status !== 'failed');
  });

  constructor() {
    effect(() => {
      if (!this.hasPendingTests()) return;
      const timer = setInterval(() => {
        if (!this.hasPendingTests()) {
          clearInterval(timer);
          return;
        }
        this.reloadTrigger$.next();
      }, 3000);
      return () => clearInterval(timer);
    });
  }

  readonly pendingId = signal<Set<number>>(new Set());
  readonly searchTerm = signal<string>('');
  readonly activeStatuses = signal<Set<'pass' | 'fail' | 'new'>>(new Set());

  private classifyTest(testRow: TestRow): 'pass' | 'fail' | 'new' {
    if (testRow.baseline_url === null) return 'new';
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
    return this.sortedTests()
      .filter((testRow) => testRow.name.toLowerCase().includes(lowerSearchTerm))
      .filter((testRow) => {
        if (statuses.size === 0) return true;
        const cls = this.classifyTest(testRow);
        return statuses.has(cls) || (cls === 'new' && statuses.has('fail'));
      });
  });

  ngAfterViewInit(): void {
    const saved = this.sortState();
    if (saved.active) {
      this.sort?.sort({
        id: saved.active,
        start: saved.direction as 'asc' | 'desc',
        disableClear: false,
      });
    }
  }

  onSortChange(sort: Sort): void {
    this.sortState.set(sort);
    this.sortService.save('run-tests', sort);
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  toggleStatus(status: 'pass' | 'fail' | 'new'): void {
    this.activeStatuses.update((currentStatuses) => {
      const next = new Set(currentStatuses);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
      }
      return next;
    });
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
          this.promotedIds.update((currentStatuses) => new Set([...currentStatuses, test.id]));
          this.pendingId.update((currentStatuses) => {
            const next = new Set(currentStatuses);
            next.delete(test.id);
            return next;
          });
          this.reloadTrigger$.next();
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
