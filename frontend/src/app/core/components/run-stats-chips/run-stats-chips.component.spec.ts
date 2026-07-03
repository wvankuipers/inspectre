import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { RunStatsChipsComponent } from './run-stats-chips.component';
import { RunSummary } from '../../models/api';

const base: RunSummary = {
  id: 1, sequential_id: 1, created_at: '2026-01-01T00:00:00Z',
  passing: 0, failing: 0, unbaselined: 0,
};

describe('RunStatsChipsComponent', () => {
  let fixture: ComponentFixture<RunStatsChipsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RunStatsChipsComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(RunStatsChipsComponent);
  });

  it('shows chip-pass with count when passing > 0', () => {
    fixture.componentRef.setInput('stats', { ...base, passing: 3 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const chip = el.querySelector('.chip-pass');
    expect(chip).not.toBeNull();
    expect(chip!.textContent).toContain('3');
  });

  it('shows chip-fail with count when failing > 0', () => {
    fixture.componentRef.setInput('stats', { ...base, failing: 2 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const chip = el.querySelector('.chip-fail');
    expect(chip).not.toBeNull();
    expect(chip!.textContent).toContain('2');
  });

  it('shows chip-new with count when unbaselined > 0', () => {
    fixture.componentRef.setInput('stats', { ...base, unbaselined: 1 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const chip = el.querySelector('.chip-new');
    expect(chip).not.toBeNull();
    expect(chip!.textContent).toContain('1');
  });

  it('shows chip-none "No tests" when all counts are zero', () => {
    fixture.componentRef.setInput('stats', { ...base });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.chip-none')?.textContent?.trim()).toBe('No tests');
  });

  it('shows multiple chips simultaneously when multiple counts are non-zero', () => {
    fixture.componentRef.setInput('stats', { ...base, passing: 2, failing: 1, unbaselined: 3 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.chip-pass')).not.toBeNull();
    expect(el.querySelector('.chip-fail')).not.toBeNull();
    expect(el.querySelector('.chip-new')).not.toBeNull();
    expect(el.querySelector('.chip-none')).toBeNull();
  });
});
