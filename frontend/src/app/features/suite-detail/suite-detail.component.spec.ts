import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { SuiteDetail } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';
import { SuiteDetailComponent } from './suite-detail.component';

const SUITE: SuiteDetail = {
  id: 1,
  name: 'Web',
  slug: 'web',
  project_name: 'Acme Corp',
  latest_runs: [
    {
      id: 1,
      sequential_id: 1,
      created_at: '2026-01-01T00:00:00Z',
      passing: 5,
      failing: 0,
      unbaselined: 0,
    },
    {
      id: 2,
      sequential_id: 3,
      created_at: '2026-01-03T00:00:00Z',
      passing: 3,
      failing: 2,
      unbaselined: 2,
    },
    {
      id: 3,
      sequential_id: 2,
      created_at: '2026-01-02T00:00:00Z',
      passing: 4,
      failing: 1,
      unbaselined: 0,
    },
  ],
  baselines: [
    {
      id: 1,
      name: 'Zeta',
      browser: 'firefox',
      size: '1280x800',
      key: 'z',
      screenshot_url: null,
      thumbnail_url: null,
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2,
      name: 'Alpha',
      browser: 'chrome',
      size: '1280x800',
      key: 'a',
      screenshot_url: null,
      thumbnail_url: null,
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
};

describe('SuiteDetailComponent sorting', () => {
  let sortServiceGet: ReturnType<typeof vi.fn>;
  let sortServiceSave: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    sortServiceGet = vi.fn((key: string) => {
      if (key === 'suite-runs') return { active: 'seq', direction: 'desc' };
      if (key === 'suite-baselines') return { active: 'name', direction: 'asc' };
      return { active: '', direction: '' };
    });
    sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [SuiteDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => 'test' } },
            paramMap: of({ get: (k: string) => (k === 'projectSlug' ? 'proj' : 'web') }),
          },
        },
        { provide: InspectreApiService, useValue: { suite: () => of(SUITE) } },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('restores runs sort from SortStateService on init', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(sortServiceGet).toHaveBeenCalledWith('suite-runs');
  });

  it('restores baselines sort from SortStateService on init', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(sortServiceGet).toHaveBeenCalledWith('suite-baselines');
  });

  it('sortedRuns() returns runs sorted by seq desc by default', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component['runSortState'].set({ active: 'seq', direction: 'desc' });
    const seqs = component.sortedRuns().map((r) => r.sequential_id);
    expect(seqs).toEqual([3, 2, 1]);
  });

  it('baselinesDataSource is populated with suite baselines on load', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    const ds = component.baselinesDataSource;
    expect(ds.data.length).toBe(2);
  });

  it('saves runs sort on change', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onRunSortChange({ active: 'when', direction: 'asc' });
    expect(sortServiceSave).toHaveBeenCalledWith('suite-runs', {
      active: 'when',
      direction: 'asc',
    });
  });

  it('saves baselines sort to SortStateService on sort change', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.baselinesSort!.sort({ id: 'browser', start: 'asc', disableClear: false });
    expect(sortServiceSave).toHaveBeenCalledWith(
      'suite-baselines',
      expect.objectContaining({ active: 'browser' }),
    );
  });

  it('baselinesDataSource filterPredicate matches on name only', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    const ds = component.baselinesDataSource;
    expect(ds.filterPredicate(SUITE.baselines[0], 'zeta')).toBe(true);
    expect(ds.filterPredicate(SUITE.baselines[0], 'chrome')).toBe(false); // browser not searched
  });

  it('renders project name in h1 heading', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const h1 = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(h1?.textContent?.trim()).toBe('Acme Corp — Web');
  });
});

describe('SuiteDetailComponent baselines search', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const sortServiceGet = vi.fn((key: string) => {
      if (key === 'suite-runs') return { active: 'seq', direction: 'desc' };
      if (key === 'suite-baselines') return { active: 'name', direction: 'asc' };
      return { active: '', direction: '' };
    });
    const sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [SuiteDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => 'test' } },
            paramMap: of({ get: (k: string) => (k === 'projectSlug' ? 'proj' : 'web') }),
          },
        },
        { provide: InspectreApiService, useValue: { suite: () => of(SUITE) } },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  it('shows only matching baselines when search term matches name', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onBaselinesSearch('alpha');
    fixture.detectChanges();
    await fixture.whenStable();
    const rows = component.baselinesDataSource.filteredData;
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe('Alpha');
  });

  it('shows no results when baselines search matches nothing', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onBaselinesSearch('zzznomatch');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(component.baselinesDataSource.filteredData.length).toBe(0);
    expect(component.baselinesSearchTerm()).toBe('zzznomatch');
  });
});

describe('SuiteDetailComponent unbaselined chip', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const sortServiceGet = vi.fn((key: string) => {
      if (key === 'suite-runs') return { active: 'seq', direction: 'desc' };
      if (key === 'suite-baselines') return { active: 'name', direction: 'asc' };
      return { active: '', direction: '' };
    });
    const sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [SuiteDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => 'test' } },
            paramMap: of({ get: (k: string) => (k === 'projectSlug' ? 'proj' : 'web') }),
          },
        },
        { provide: InspectreApiService, useValue: { suite: () => of(SUITE) } },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  it('renders "N new" chip for runs with unbaselined > 0', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const chips = (fixture.nativeElement as HTMLElement).querySelectorAll('span.chip');
    const texts = Array.from(chips).map((c) => c.textContent?.trim());
    expect(texts).toContain('2 new');
  });

  it('does not render "new" chip for runs with unbaselined === 0', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const chips = (fixture.nativeElement as HTMLElement).querySelectorAll('span.chip');
    const texts = Array.from(chips).map((c) => c.textContent?.trim());
    // Only run with sequential_id=3 has unbaselined=2, so exactly one "new" chip
    expect(texts.filter((t) => t?.includes('new')).length).toBe(1);
  });
});

describe('SuiteDetailComponent tabs', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const sortServiceGet = vi.fn((key: string) => {
      if (key === 'suite-runs') return { active: 'seq', direction: 'desc' };
      if (key === 'suite-baselines') return { active: 'name', direction: 'asc' };
      return { active: '', direction: '' };
    });
    const sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [SuiteDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => 'test' } },
            paramMap: of({ get: (k: string) => (k === 'projectSlug' ? 'proj' : 'web') }),
          },
        },
        { provide: InspectreApiService, useValue: { suite: () => of(SUITE) } },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  it('renders both tab labels', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const labels = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.mat-mdc-tab .mdc-tab__text-label'),
    ).map((el) => el.textContent?.trim());
    expect(labels).toContain('Latest runs');
    expect(labels).toContain('Baselines');
  });

  it('renders baselines search field after switching to Baselines tab', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    // Click the Baselines tab to activate it
    const tabs = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.mat-mdc-tab'),
    ) as HTMLElement[];
    const baselinesTab = tabs.find((t) => t.textContent?.includes('Baselines'));
    baselinesTab?.click();
    fixture.detectChanges();
    await fixture.whenStable();
    const searchField = (fixture.nativeElement as HTMLElement).querySelector('app-search-field');
    expect(searchField).not.toBeNull();
  });
});

describe('SuiteDetailComponent API failure', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const sortServiceGet = vi.fn((key: string) => {
      if (key === 'suite-runs') return { active: 'seq', direction: 'desc' };
      if (key === 'suite-baselines') return { active: 'name', direction: 'asc' };
      return { active: '', direction: '' };
    });
    const sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [SuiteDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => 'test' } },
            paramMap: of({ get: (k: string) => (k === 'projectSlug' ? 'proj' : 'web') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { suite: () => throwError(() => new Error('network')) },
        },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  it('renders without crashing when api.suite() errors', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('does not render suite h1 when api.suite() errors (suite is null)', async () => {
    const fixture = TestBed.createComponent(SuiteDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const h1 = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(h1).toBeNull();
  });
});
