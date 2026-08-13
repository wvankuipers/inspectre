import { TestBed } from '@angular/core/testing';
import { MatSort } from '@angular/material/sort';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
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
          sequential_id: 1,
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
          created_at: '2026-01-01T00:00:00Z',
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
          sequential_id: 1,
          created_at: '2026-01-01T00:00:00Z',
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
