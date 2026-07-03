import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { describe, it, expect, vi } from 'vitest';
import { ImageViewerComponent, ImageViewerData } from './image-viewer.component';
import { TestRow } from '../../models/api';

const makeTest = (overrides: Partial<TestRow> = {}): TestRow => ({
  id: 1, name: 'about', browser: 'Chrome', size: '1024', source_url: '', status: 'done', diff: 2.3,
  passed: false, key: 'a', is_baseline_source: false, fuzz_level: '0',
  highlight_colour: '', crop_area: '',
  screenshot_url: 'http://s3/a.png',
  baseline_url: 'http://s3/a-base.png',
  diff_url: 'http://s3/a-diff.png',
  screenshot_thumb_url: 'http://s3/a-thumb.png',
  baseline_thumb_url: 'http://s3/a-base-thumb.png',
  diff_thumb_url: 'http://s3/a-diff-thumb.png',
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const setup = async (data: ImageViewerData): Promise<ComponentFixture<ImageViewerComponent>> => {
  await TestBed.configureTestingModule({
    imports: [ImageViewerComponent],
    providers: [
      provideNoopAnimations(),
      { provide: MAT_DIALOG_DATA, useValue: data },
      { provide: MatDialogRef, useValue: { close: vi.fn() } },
    ],
  }).compileComponents();
  const fixture = TestBed.createComponent(ImageViewerComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
};

describe('ImageViewerComponent', () => {
  it('renders test name, browser, and size in header', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'comparison' });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('about');
    expect(el.textContent).toContain('Chrome');
    expect(el.textContent).toContain('1024');
  });

  it('shows correct initial slot label', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'diff' });
    const el = fixture.nativeElement as HTMLElement;
    const label = el.querySelector('.viewer-slot-label');
    expect(label?.textContent?.trim()).toBe('Diff');
  });

  it('next button advances slot from Baseline to Comparison', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'baseline' });
    const el = fixture.nativeElement as HTMLElement;
    const nextBtn = el.querySelector('[data-testid="next-btn"]') as HTMLButtonElement;
    nextBtn.click();
    fixture.detectChanges();
    expect(el.querySelector('.viewer-slot-label')?.textContent?.trim()).toBe('Comparison');
  });

  it('prev button is absent on the first slot', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'baseline' });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="prev-btn"]')).toBeNull();
  });

  it('next button is absent on the last slot', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'compare' });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="next-btn"]')).toBeNull();
  });

  it('availableSlots excludes baseline when baseline_url is null', async () => {
    const fixture = await setup({
      tests: [makeTest({ baseline_url: null, baseline_thumb_url: null, diff_url: null, diff_thumb_url: null })],
      index: 0,
      slot: 'comparison',
    });
    expect(fixture.componentInstance.availableSlots()).toEqual(['comparison']);
  });

  it('ArrowRight key advances slot', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'baseline' });
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.viewer-slot-label')?.textContent?.trim()).toBe('Comparison');
  });

  it('availableSlots includes compare when baseline_url is non-null', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'comparison' });
    expect(fixture.componentInstance.availableSlots()).toContain('compare');
  });

  it('availableSlots excludes compare when baseline_url is null', async () => {
    const fixture = await setup({
      tests: [makeTest({ baseline_url: null, baseline_thumb_url: null, diff_url: null, diff_thumb_url: null })],
      index: 0,
      slot: 'comparison',
    });
    expect(fixture.componentInstance.availableSlots()).not.toContain('compare');
  });

  it('currentUrl returns null for compare slot', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'compare' });
    expect(fixture.componentInstance.currentUrl()).toBeNull();
  });

  it('compareRightUrl returns screenshot_url when compareTarget is comparison', async () => {
    const test = makeTest();
    const fixture = await setup({ tests: [test], index: 0, slot: 'compare' });
    const comp = fixture.componentInstance;
    comp['compareTarget'].set('comparison');
    expect(comp.compareRightUrl()).toBe(test.screenshot_url);
  });

  it('compareRightUrl returns diff_url when compareTarget is diff', async () => {
    const test = makeTest();
    const fixture = await setup({ tests: [test], index: 0, slot: 'compare' });
    const comp = fixture.componentInstance;
    comp['compareTarget'].set('diff');
    expect(comp.compareRightUrl()).toBe(test.diff_url);
  });

  it('sliderPct resets to 50 when testIndex changes', async () => {
    const tests = [makeTest({ id: 1 }), makeTest({ id: 2, name: 'page2' })];
    const fixture = await setup({ tests, index: 0, slot: 'compare' });
    const comp = fixture.componentInstance;
    comp['sliderPct'].set(75);
    comp['testIndex'].set(1);
    fixture.detectChanges();
    expect(comp['sliderPct']()).toBe(50);
  });

  it('compareTarget resets to comparison when testIndex changes', async () => {
    const tests = [makeTest({ id: 1 }), makeTest({ id: 2, name: 'page2' })];
    const fixture = await setup({ tests, index: 0, slot: 'compare' });
    const comp = fixture.componentInstance;
    comp['compareTarget'].set('diff');
    comp['testIndex'].set(1);
    fixture.detectChanges();
    expect(comp['compareTarget']()).toBe('comparison');
  });

  it('vs-Diff button is disabled when diff_url is null', async () => {
    const fixture = await setup({
      tests: [makeTest({ diff_url: null, diff_thumb_url: null })],
      index: 0,
      slot: 'compare',
    });
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const buttons = Array.from(el.querySelectorAll('button')) as HTMLButtonElement[];
    const vsDiff = buttons.find(b => b.textContent?.includes('vs Diff'));
    expect(vsDiff?.disabled).toBe(true);
  });

  it('viewer image wrapper has img-skeleton class before load fires', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'comparison' });
    const el = fixture.nativeElement as HTMLElement;
    const wrapper = el.querySelector('.viewer-image .img-skeleton, .viewer-image .img-loaded');
    expect(wrapper?.classList.contains('img-skeleton')).toBe(true);
  });

  it('viewer image wrapper switches to img-loaded after onImgLoad fires', async () => {
    const fixture = await setup({ tests: [makeTest()], index: 0, slot: 'comparison' });
    const comp = fixture.componentInstance;
    expect(comp.viewerLoaded()).toBe(false);
    comp.onImgLoad();
    fixture.detectChanges();
    expect(comp.viewerLoaded()).toBe(true);
  });
});
