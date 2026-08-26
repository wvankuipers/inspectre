import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { BreadcrumbComponent } from '../../core/components/breadcrumb/breadcrumb.component';
import { TestHistory } from '../../core/models/api';

@Component({
  selector: 'app-test-detail',
  standalone: true,
  imports: [DatePipe, RouterLink, BreadcrumbComponent],
  templateUrl: './test-detail.component.html',
  styleUrl: './test-detail.component.scss',
})
export class TestDetailComponent {
  private route = inject(ActivatedRoute);
  private api = inject(InspectreApiService);

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
