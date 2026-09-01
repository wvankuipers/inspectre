import { By } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { MatSort } from '@angular/material/sort';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { delay, of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { Project } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';
import { ProjectsListComponent } from './projects-list.component';

const PROJECTS: Project[] = [
  {
    id: 1,
    name: 'Beta',
    slug: 'beta',
    suites: [
      {
        id: 10,
        name: 'S1',
        slug: 's1',
        latest_run: {
          id: 1,
          sequential_id: 5,
          created_at: '2026-01-01T00:00:00Z',
          passing: 0,
          failing: 3,
          unbaselined: 3,
        },
      },
    ],
  },
  {
    id: 2,
    name: 'Alpha',
    slug: 'alpha',
    suites: [
      {
        id: 20,
        name: 'S2',
        slug: 's2',
        latest_run: {
          id: 2,
          sequential_id: 1,
          created_at: '2026-01-05T00:00:00Z',
          passing: 6,
          failing: 0,
          unbaselined: 0,
        },
      },
    ],
  },
  {
    id: 3,
    name: 'Gamma',
    slug: 'gamma',
    suites: [
      {
        id: 30,
        name: 'S3',
        slug: 's3',
        latest_run: {
          id: 3,
          sequential_id: 3,
          created_at: '2026-01-03T00:00:00Z',
          passing: 2,
          failing: 3,
          unbaselined: 0,
        },
      },
    ],
  },
  {
    id: 4,
    name: 'Delta',
    slug: 'delta',
    suites: [{ id: 40, name: 'S4', slug: 's4', latest_run: null }],
  },
];

describe('ProjectsListComponent sorting', () => {
  let getSpy: ReturnType<typeof vi.fn>;
  let saveSpy: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    getSpy = vi.fn().mockReturnValue({ active: '', direction: '' });
    saveSpy = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS) } },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('restores sort from SortStateService on init', async () => {
    getSpy.mockReturnValue({ active: 'project', direction: 'asc' });
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(getSpy).toHaveBeenCalledWith('projects');
  });

  it('saves sort to SortStateService on sort change', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    (component as unknown as { sort: MatSort }).sort.sort({
      id: 'project',
      start: 'asc',
      disableClear: false,
    });
    expect(saveSpy).toHaveBeenCalledWith(
      'projects',
      expect.objectContaining({ active: 'project' }),
    );
  });

  it('sortingDataAccessor returns project name for project column', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    const ds = component.dataSource;
    const row = ds.data[0]; // Beta row
    expect(ds.sortingDataAccessor(row, 'project')).toBe('Beta');
    expect(ds.sortingDataAccessor(row, 'suite')).toBe('S1');
  });

  it('sortingDataAccessor sorts the latestRun column by created_at, not sequential_id', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    const ds = component.dataSource;
    const row = ds.data[0]; // Beta row: sequential_id 5, created_at 2026-01-01 (earliest)
    // Beta has the *highest* sequential_id but the *earliest* created_at, so sorting
    // by date vs. by run number gives different results — this distinguishes them.
    expect(ds.sortingDataAccessor(row, 'latestRun')).toBe(
      Date.parse('2026-01-01T00:00:00Z'),
    );
    expect(ds.sortingDataAccessor(row, 'latestRun')).not.toBe(5);
  });

  it('actually reorders the connected table rows when a real MatSort is triggered', async () => {
    // Real project data loads asynchronously over HTTP. Delay the mocked
    // response so it resolves *after* the first view check (the same timing
    // that exposed the original bug: the @if-gated <table>/MatSort don't
    // exist yet when ngAfterViewInit fires).
    await TestBed.resetTestingModule()
      .configureTestingModule({
        imports: [ProjectsListComponent],
        providers: [
          provideNoopAnimations(),
          provideRouter([]),
          { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS).pipe(delay(0)) } },
          { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
        ],
      })
      .compileComponents();

    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges(); // first view check — table not rendered yet, data still pending
    await new Promise((resolve) => setTimeout(resolve, 10)); // async data arrives
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();

    const matSortDebugEl = fixture.debugElement.query(By.directive(MatSort));
    expect(matSortDebugEl).toBeTruthy();
    const matSort = matSortDebugEl.injector.get(MatSort);

    const renderedProjectNames = (): string[] =>
      Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll(
          'tr.mat-mdc-row td.mat-column-project, tr.mat-row td.mat-column-project',
        ),
      ).map((cell) => cell.textContent?.trim() ?? '');

    // Unsorted order from the API fixture is Beta, Alpha, Gamma, Delta.
    expect(renderedProjectNames()).toEqual(['Beta', 'Alpha', 'Gamma', 'Delta']);

    matSort.sort({ id: 'project', start: 'asc', disableClear: false });
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(renderedProjectNames()).toEqual(['Alpha', 'Beta', 'Delta', 'Gamma']);
  });

  it('reorders rows by created_at (not sequential_id) when sorting the Last run column', async () => {
    // Fixture run numbers vs. dates deliberately diverge:
    //   Beta:  sequential_id 5, created_at 2026-01-01 (earliest)
    //   Alpha: sequential_id 1, created_at 2026-01-05 (latest)
    //   Gamma: sequential_id 3, created_at 2026-01-03 (middle)
    //   Delta: no latest_run
    // Sorting ascending by sequential_id would give: Delta, Alpha, Gamma, Beta.
    // Sorting ascending by created_at (the desired behavior) gives: Delta, Beta, Gamma, Alpha.
    await TestBed.resetTestingModule()
      .configureTestingModule({
        imports: [ProjectsListComponent],
        providers: [
          provideNoopAnimations(),
          provideRouter([]),
          { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS).pipe(delay(0)) } },
          { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
        ],
      })
      .compileComponents();

    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges(); // first view check — table not rendered yet, data still pending
    await new Promise((resolve) => setTimeout(resolve, 10)); // async data arrives
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();

    const matSortDebugEl = fixture.debugElement.query(By.directive(MatSort));
    expect(matSortDebugEl).toBeTruthy();
    const matSort = matSortDebugEl.injector.get(MatSort);

    const renderedProjectNames = (): string[] =>
      Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll(
          'tr.mat-mdc-row td.mat-column-project, tr.mat-row td.mat-column-project',
        ),
      ).map((cell) => cell.textContent?.trim() ?? '');

    matSort.sort({ id: 'latestRun', start: 'asc', disableClear: false });
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(renderedProjectNames()).toEqual(['Delta', 'Beta', 'Gamma', 'Alpha']);
  });

  it('restores a saved ascending sort on reload without flipping it to descending', async () => {
    // Regression test: the template's [matSortActive]/[matSortDirection]
    // bindings already set MatSort.active/direction from the saved state
    // before the @ViewChild setter runs. If the setter also imperatively
    // calls sort.sort({ id: saved.active, ... }), MatSort sees active is
    // already equal to the id and takes its "toggle to next direction"
    // branch instead of applying saved.direction — silently flipping a
    // saved ascending sort to descending on every reload.
    getSpy.mockReturnValue({ active: 'project', direction: 'asc' });

    await TestBed.resetTestingModule()
      .configureTestingModule({
        imports: [ProjectsListComponent],
        providers: [
          provideNoopAnimations(),
          provideRouter([]),
          { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS).pipe(delay(0)) } },
          { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
        ],
      })
      .compileComponents();

    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges(); // first view check — table not rendered yet, data still pending
    await new Promise((resolve) => setTimeout(resolve, 10)); // async data arrives
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();

    const renderedProjectNames = (): string[] =>
      Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll(
          'tr.mat-mdc-row td.mat-column-project, tr.mat-row td.mat-column-project',
        ),
      ).map((cell) => cell.textContent?.trim() ?? '');

    // Saved sort is { active: 'project', direction: 'asc' }, so rows must
    // render alphabetically ascending by project name, NOT descending.
    expect(renderedProjectNames()).toEqual(['Alpha', 'Beta', 'Delta', 'Gamma']);
  });
});

describe('ProjectsListComponent search', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const getSpy = vi.fn().mockReturnValue({ active: '', direction: '' });
    const saveSpy = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS) } },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
      ],
    }).compileComponents();
  });

  it('shows only matching rows when search term matches project name', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onSearch('alpha');
    fixture.detectChanges();
    await fixture.whenStable();
    const rows = component.dataSource.filteredData;
    expect(rows.length).toBe(1);
    expect(rows[0].project.name).toBe('Alpha');
  });

  it('shows no-data row when search term matches nothing', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onSearch('zzznomatch');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(component.dataSource.filteredData.length).toBe(0);
    expect(component.searchTerm()).toBe('zzznomatch');
  });
});

describe('ProjectsListComponent unbaselined chip', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const getSpy = vi.fn().mockReturnValue({ active: '', direction: '' });
    const saveSpy = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS) } },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
      ],
    }).compileComponents();
  });

  it('renders "N new" chip when unbaselined > 0', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const chips = (fixture.nativeElement as HTMLElement).querySelectorAll('span.chip');
    const texts = Array.from(chips).map((c) => c.textContent?.trim());
    expect(texts).toContain('3 new');
  });

  it('does not render "new" chip when unbaselined === 0', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const chips = (fixture.nativeElement as HTMLElement).querySelectorAll('span.chip');
    const texts = Array.from(chips).map((c) => c.textContent?.trim());
    expect(texts.filter((t) => t?.includes('new')).length).toBe(1); // only Beta row has chip
  });
});

describe('ProjectsListComponent status filter', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const getSpy = vi.fn().mockReturnValue({ active: '', direction: '' });
    const saveSpy = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS) } },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
      ],
    }).compileComponents();
  });

  it('shows all rows when no status filter is active', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.visibleRows().length).toBe(4);
  });

  it('shows only passing rows when pass filter is active', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.detectChanges();
    const rows = fixture.componentInstance.visibleRows();
    expect(rows.length).toBe(1);
    expect(rows[0].project.name).toBe('Alpha');
  });

  it('shows failing rows (including unbaselined ones) when fail filter is active', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('fail');
    fixture.detectChanges();
    const rows = fixture.componentInstance.visibleRows();
    const names = rows.map((r) => r.project.name);
    // Beta is unbaselined (which also counts as failing on the backend), so it
    // should show up under "Fail" too, matching run-detail's behavior.
    expect(names).toContain('Gamma');
    expect(names).toContain('Beta');
    expect(rows.length).toBe(2);
  });

  it('shows only new rows when new filter is active', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('new');
    fixture.detectChanges();
    const rows = fixture.componentInstance.visibleRows();
    expect(rows.length).toBe(1);
    expect(rows[0].project.name).toBe('Beta');
  });

  it('hides rows with no latest_run when any filter is active', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.detectChanges();
    const names = fixture.componentInstance.visibleRows().map((r) => r.project.name);
    expect(names).not.toContain('Delta');
  });

  it('clears filter when same status is toggled twice', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.componentInstance.toggleStatus('pass');
    fixture.detectChanges();
    expect(fixture.componentInstance.visibleRows().length).toBe(4);
  });

  it('composes status filter and search as AND', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.componentInstance.onSearch('alpha');
    fixture.detectChanges();
    await fixture.whenStable();
    const rows = fixture.componentInstance.dataSource.filteredData;
    expect(rows.length).toBe(1);
    expect(rows[0].project.name).toBe('Alpha');
  });
});

describe('ProjectsListComponent query params', () => {
  afterEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  function configureWithQueryParams(
    queryParams: Record<string, string>,
    sortGet: { active: string; direction: '' | 'asc' | 'desc' } = { active: '', direction: '' },
  ) {
    localStorage.clear();
    const getSpy = vi.fn().mockReturnValue(sortGet);
    const saveSpy = vi.fn();
    const paramMap = { get: (k: string) => queryParams[k] ?? null };

    return TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: InspectreApiService, useValue: { projects: () => of(PROJECTS) } },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: paramMap },
            queryParamMap: of(paramMap),
          },
        },
      ],
    }).compileComponents();
  }

  it('seeds searchTerm, activeStatuses, and sortState from URL query params on init', async () => {
    await configureWithQueryParams({ q: 'alpha', status: 'fail,new', sort: 'suite', dir: 'desc' });
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    expect(component.searchTerm()).toBe('alpha');
    expect(component.activeStatuses()).toEqual(new Set(['fail', 'new']));
    expect(component.sortState()).toEqual({ active: 'suite', direction: 'desc' });
  });

  it('falls back to SortStateService when the URL has no sort/dir params', async () => {
    await configureWithQueryParams({}, { active: 'project', direction: 'asc' });
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.sortState()).toEqual({ active: 'project', direction: 'asc' });
  });

  it('updates the URL query params immediately when sort changes', async () => {
    await configureWithQueryParams({});
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');
    const component = fixture.componentInstance;
    (component as unknown as { sort: MatSort }).sort.sort({
      id: 'project',
      start: 'asc',
      disableClear: false,
    });
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { sort: 'project', dir: 'asc' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });

  it('updates the URL query params immediately when a status filter is toggled', async () => {
    await configureWithQueryParams({});
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');
    fixture.componentInstance.toggleStatus('fail');
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { status: 'fail' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });

  it('removes the status query param when the last active filter is toggled off', async () => {
    await configureWithQueryParams({ status: 'fail' });
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');
    fixture.componentInstance.toggleStatus('fail');
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { status: null },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });

  it('debounces search term updates to the URL by ~300ms', async () => {
    vi.useFakeTimers();
    await configureWithQueryParams({});
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');

    fixture.componentInstance.onSearch('alpha');
    expect(navigateSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(299);
    expect(navigateSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { q: 'alpha' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });
});

describe('ProjectsListComponent API failure', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();
    const getSpy = vi.fn().mockReturnValue({ active: '', direction: '' });
    const saveSpy = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ProjectsListComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: InspectreApiService,
          useValue: { projects: () => throwError(() => new Error('network')) },
        },
        { provide: SortStateService, useValue: { get: getSpy, save: saveSpy } },
      ],
    }).compileComponents();
  });

  it('renders without crashing when api.projects() errors', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('shows "No projects yet." empty state when api.projects() errors', async () => {
    const fixture = TestBed.createComponent(ProjectsListComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No projects yet.');
  });
});
