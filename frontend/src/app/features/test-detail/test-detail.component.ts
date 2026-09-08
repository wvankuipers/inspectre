import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatDialog } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { BreadcrumbComponent } from '../../core/components/breadcrumb/breadcrumb.component';
import {
  ImageViewerComponent,
  ImageViewerTest,
} from '../../core/components/image-viewer/image-viewer.component';
import { TestHistory, TestHistoryEntry } from '../../core/models/api';

@Component({
  selector: 'app-test-detail',
  standalone: true,
  imports: [DatePipe, MatTableModule, RouterLink, BreadcrumbComponent],
  templateUrl: './test-detail.component.html',
  styleUrl: './test-detail.component.scss',
})
export class TestDetailComponent {
  private route = inject(ActivatedRoute);
  private api = inject(InspectreApiService);
  private dialog = inject(MatDialog);

  readonly columns = ['run', 'date', 'thumbnail', 'status'];

  private params = toSignal(this.route.paramMap, {
    initialValue: this.route.snapshot.paramMap,
  });

  readonly projectSlug = computed(() => this.params().get('projectSlug') ?? '');
  readonly suiteSlug = computed(() => this.params().get('suiteSlug') ?? '');
  readonly key = computed(() => this.params().get('key') ?? '');

  readonly loadError = signal<boolean>(false);

  private historyData = signal<TestHistory | undefined>(undefined);

  readonly history = computed(() => this.historyData() ?? null);

  readonly thumbLoaded = signal<Set<string>>(new Set<string>());

  onImgLoad(src: string): void {
    this.thumbLoaded.update((previouslyLoaded) => new Set(previouslyLoaded).add(src));
  }

  onImgError(event: Event): void {
    const img = event.target as HTMLImageElement;
    if (img.dataset['failed']) return;
    img.dataset['failed'] = '1';
    img.src = '/image_not_found.jpg';
  }

  trackByEntryId(_index: number, entry: TestHistoryEntry): number {
    return entry.id;
  }

  openViewer(entry: TestHistoryEntry): void {
    const h = this.history();
    if (!h) return;
    const tests: ImageViewerTest[] = h.runs.map((r) => ({
      name: h.name,
      browser: h.browser,
      size: h.size,
      diff: r.diff,
      passed: r.original_passed ?? false,
      screenshot_url: r.screenshot_url,
      baseline_url: r.baseline_url,
      diff_url: r.diff_url,
    }));
    const index = h.runs.indexOf(entry);
    this.dialog.open(ImageViewerComponent, {
      data: { tests, index, slot: 'comparison' },
      maxWidth: '100vw',
      maxHeight: '100vh',
      width: '100vw',
      height: '100vh',
      panelClass: 'image-viewer-panel',
    });
  }

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((params) => {
          this.loadError.set(false);
          return this.api
            .testHistory(params.get('projectSlug')!, params.get('suiteSlug')!, params.get('key')!)
            .pipe(
              catchError(() => {
                this.loadError.set(true);
                return of<TestHistory | null>(null);
              }),
            );
        }),
        takeUntilDestroyed(),
      )
      .subscribe((historyData) => {
        this.historyData.set(historyData ?? undefined);
      });
  }
}
