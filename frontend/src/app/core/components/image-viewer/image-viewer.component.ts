import { Component, HostListener, OnDestroy, computed, effect, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { TestRow } from '../../models/api';

export type ImageSlot = 'baseline' | 'comparison' | 'diff' | 'compare';

export interface ImageViewerData {
  tests: TestRow[];
  index: number;
  slot: ImageSlot;
}

const SLOT_LABELS: Record<ImageSlot, string> = {
  baseline: 'Baseline',
  comparison: 'Comparison',
  diff: 'Diff',
  compare: 'Compare',
};

@Component({
  selector: 'app-image-viewer',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule],
  templateUrl: './image-viewer.component.html',
  styleUrl: './image-viewer.component.scss',
})
export class ImageViewerComponent implements OnDestroy {
  private dialogRef = inject(MatDialogRef<ImageViewerComponent>);
  readonly data = inject<ImageViewerData>(MAT_DIALOG_DATA);

  readonly testIndex = signal<number>(this.data.index);
  readonly slot = signal<ImageSlot>(this.data.slot);
  readonly compareTarget = signal<'comparison' | 'diff'>('comparison');
  readonly sliderPct = signal<number>(50);
  readonly viewerLoaded = signal<boolean>(false);

  readonly currentTest = computed(() => this.data.tests[this.testIndex()]);

  readonly availableSlots = computed<ImageSlot[]>(() => {
    const test = this.currentTest();
    const slots: ImageSlot[] = [];
    if (test.baseline_url) slots.push('baseline');
    slots.push('comparison');
    if (test.diff_url) slots.push('diff');
    if (test.baseline_url) slots.push('compare');
    return slots;
  });

  readonly currentUrl = computed<string | null>(() => {
    const test = this.currentTest();
    const currentSlot = this.slot();
    if (currentSlot === 'baseline') return test.baseline_url;
    if (currentSlot === 'comparison') return test.screenshot_url;
    if (currentSlot === 'diff') return test.diff_url;
    return null; // 'compare' renders its own block
  });

  readonly compareRightUrl = computed<string | null>(() => {
    const test = this.currentTest();
    return this.compareTarget() === 'comparison' ? test.screenshot_url : test.diff_url;
  });

  constructor() {
    effect(() => {
      this.testIndex(); // track testIndex changes
      this.slot();      // track slot changes
      this.viewerLoaded.set(false);
      this.sliderPct.set(50);
      this.compareTarget.set('comparison');
    });
  }

  readonly slotIndex = computed(() => this.availableSlots().indexOf(this.slot()));

  readonly currentSlotLabel = computed(() => SLOT_LABELS[this.slot()]);

  readonly prevSlotLabel = computed<string | null>(() => {
    const slotIdx = this.slotIndex();
    if (slotIdx <= 0) return null;
    return SLOT_LABELS[this.availableSlots()[slotIdx - 1]];
  });

  readonly nextSlotLabel = computed<string | null>(() => {
    const slots = this.availableSlots();
    const slotIdx = this.slotIndex();
    if (slotIdx >= slots.length - 1) return null;
    return SLOT_LABELS[slots[slotIdx + 1]];
  });

  readonly slotCounter = computed(() => `${this.slotIndex() + 1} / ${this.availableSlots().length}`);

  prevSlot(): void {
    const slotIdx = this.slotIndex();
    if (slotIdx > 0) this.slot.set(this.availableSlots()[slotIdx - 1]);
  }

  nextSlot(): void {
    const slots = this.availableSlots();
    const slotIdx = this.slotIndex();
    if (slotIdx < slots.length - 1) this.slot.set(slots[slotIdx + 1]);
  }

  close(): void {
    this.dialogRef.close();
  }

  onImgLoad(): void {
    this.viewerLoaded.set(true);
  }

  onImgError(event: Event): void {
    const img = event.target as HTMLImageElement;
    if (img.dataset['failed']) return;
    img.dataset['failed'] = '1';
    img.src = '/image_not_found.jpg';
  }

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'ArrowLeft') this.prevSlot();
    if (event.key === 'ArrowRight') this.nextSlot();
  }

  onSliderKeydown(event: KeyboardEvent): void {
    const step = event.shiftKey ? 1 : 5;
    if (event.key === 'ArrowLeft') {
      event.stopPropagation();
      this.sliderPct.set(Math.max(0, this.sliderPct() - step));
    } else if (event.key === 'ArrowRight') {
      event.stopPropagation();
      this.sliderPct.set(Math.min(100, this.sliderPct() + step));
    } else if (event.key === 'Home') {
      event.stopPropagation();
      this.sliderPct.set(0);
    } else if (event.key === 'End') {
      event.stopPropagation();
      this.sliderPct.set(100);
    }
  }

  private cleanupDrag: (() => void) | null = null;

  ngOnDestroy(): void {
    this.cleanupDrag?.();
  }

  onDragStart(event: MouseEvent): void {
    event.preventDefault();
    const container = (event.currentTarget as HTMLElement);
    const onMove = (e: MouseEvent) => this.updateSlider(e.clientX, container);
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      this.cleanupDrag = null;
    };
    this.cleanupDrag?.();
    this.cleanupDrag = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    this.updateSlider(event.clientX, container);
  }

  onTouchStart(event: TouchEvent): void {
    event.preventDefault();
    const container = (event.currentTarget as HTMLElement);
    const onMove = (e: TouchEvent) => this.updateSlider(e.touches[0].clientX, container);
    const onEnd = () => {
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
      this.cleanupDrag = null;
    };
    this.cleanupDrag?.();
    this.cleanupDrag = () => {
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
    };
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onEnd);
    this.updateSlider(event.touches[0].clientX, container);
  }

  private updateSlider(clientX: number, container: HTMLElement): void {
    const containerRect = container.getBoundingClientRect();
    const sliderPercentage = ((clientX - containerRect.left) / containerRect.width) * 100;
    this.sliderPct.set(Math.min(100, Math.max(0, sliderPercentage)));
  }
}
