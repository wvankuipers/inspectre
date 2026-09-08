import { TestBed } from '@angular/core/testing';
import { MatSort } from '@angular/material/sort';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { ProjectDetail } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';
import { ProjectDetailComponent } from './project-detail.component';

const PROJECT: ProjectDetail = {
  id: 1,
  name: 'Acme',
  slug: 'acme',
  suites: [
    {
      id: 10,
      name: 'Desktop',
      slug: 'desktop',
      latest_run: {
        id: 1,
        sequential_id: 1,
        created_at: '2026-01-01T00:00:00Z',
        passing: 5,
        failing: 0,
        unbaselined: 0,
      },
    },
    {
      id: 11,
      name: 'Mobile',
      slug: 'mobile',
      latest_run: null,
    },
    {
      id: 12,
      name: 'Tablet',
      slug: 'tablet',
      latest_run: {
        id: 2,
        sequential_id: 2,
        created_at: '2026-01-03T00:00:00Z',
        passing: 2,
        failing: 3,
        unbaselined: 0,
      },
    },
    {
      id: 13,
      name: 'Watch',
      slug: 'watch',
      latest_run: {
        id: 3,
        sequential_id: 3,
        created_at: '2026-01-02T00:00:00Z',
        passing: 0,
        failing: 0,
        unbaselined: 2,
      },
    },
  ],
};

function paramMapOf(values: Record<string, string>) {
  return { get: (k: string) => values[k] ?? null };
}

function configureModule(opts: {
  projectDetail?: () => ReturnType<InspectreApiService['projectDetail']>;
  sortGet?: ReturnType<typeof vi.fn>;
  sortSave?: ReturnType<typeof vi.fn>;
  queryParams?: Record<string, string>;
  projectSlug?: string;
}) {
  localStorage.clear();
  const sortServiceGet = opts.sortGet ?? vi.fn().mockReturnValue({ active: '', direction: '' });
  const sortServiceSave = opts.sortSave ?? vi.fn();
  const queryParamMap = paramMapOf(opts.queryParams ?? {});
  const projectSlug = opts.projectSlug ?? 'acme';

  return TestBed.configureTestingModule({
    imports: [ProjectDetailComponent],
    providers: [
      provideNoopAnimations(),
      provideRouter([]),
      {
        provide: InspectreApiService,
        useValue: { projectDetail: opts.projectDetail ?? (() => of(PROJECT)) },
      },
      { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            paramMap: paramMapOf({ projectSlug }),
            queryParamMap,
          },
          paramMap: of(paramMapOf({ projectSlug })),
          queryParamMap: of(queryParamMap),
        },
      },
    ],
  }).compileComponents();
}

describe('ProjectDetailComponent fetch', () => {
  afterEach(() => localStorage.clear());

  it('fetches project detail by projectSlug route param', async () => {
    const spy = vi.fn(() => of(PROJECT));
    await configureModule({ projectDetail: spy, projectSlug: 'acme' });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(spy).toHaveBeenCalled();
  });

  it('renders project name in an h1', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const h1 = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(h1?.textContent?.trim()).toBe('Acme');
  });

  it('renders one row per suite', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.rows().length).toBe(4);
  });
});

describe('ProjectDetailComponent breadcrumb', () => {
  afterEach(() => localStorage.clear());

  it('renders a breadcrumb back to /projects and the project name', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const breadcrumb = el.querySelector('app-breadcrumb');
    expect(breadcrumb).toBeTruthy();
    const link = Array.from(breadcrumb!.querySelectorAll('a')).find(
      (a) => a.textContent?.trim() === 'Projects',
    ) as HTMLAnchorElement | undefined;
    expect(link).toBeTruthy();
    expect(link!.getAttribute('href')).toBe('/projects');
    expect(breadcrumb!.textContent).toContain('Acme');
  });
});

describe('ProjectDetailComponent suite links', () => {
  afterEach(() => localStorage.clear());

  it('links suite name to the suite detail route', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const link = Array.from(el.querySelectorAll('td.mat-column-suite a')).find(
      (a) => a.textContent?.trim() === 'Desktop',
    ) as HTMLAnchorElement | undefined;
    expect(link).toBeTruthy();
    expect(link!.getAttribute('href')).toBe('/projects/acme/suites/desktop');
  });

  it('links the last-run cell to the specific run when latest_run is present', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const rows = Array.from(el.querySelectorAll('tr.mat-row, tr.mat-mdc-row'));
    const desktopRow = rows.find((r) => r.textContent?.includes('Desktop'));
    const link = desktopRow?.querySelector('td.mat-column-latestRun a') as HTMLAnchorElement | null;
    expect(link).toBeTruthy();
    expect(link!.getAttribute('href')).toBe('/projects/acme/suites/desktop/runs/1');
  });

  it('shows a placeholder (no crash) for the last-run cell when latest_run is null', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const rows = Array.from(el.querySelectorAll('tr.mat-row, tr.mat-mdc-row'));
    const mobileRow = rows.find((r) => r.textContent?.includes('Mobile'));
    expect(mobileRow).toBeTruthy();
    const link = mobileRow!.querySelector('td.mat-column-latestRun a');
    expect(link).toBeNull();
    expect(mobileRow!.textContent).toContain('—');
  });
});

describe('ProjectDetailComponent status chips', () => {
  afterEach(() => localStorage.clear());

  it('renders run-stats chips for a suite with a latest_run', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const rows = Array.from(el.querySelectorAll('tr.mat-row, tr.mat-mdc-row'));
    const tabletRow = rows.find((r) => r.textContent?.includes('Tablet'));
    expect(tabletRow?.querySelector('app-run-stats-chips')).toBeTruthy();
  });

  it('does not render run-stats chips for a suite with no runs yet, and shows a neutral placeholder', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const rows = Array.from(el.querySelectorAll('tr.mat-row, tr.mat-mdc-row'));
    const mobileRow = rows.find((r) => r.textContent?.includes('Mobile'));
    expect(mobileRow?.querySelector('app-run-stats-chips')).toBeFalsy();
    expect(mobileRow?.textContent).toContain('No runs yet');
  });
});

describe('ProjectDetailComponent sorting', () => {
  afterEach(() => localStorage.clear());

  it('restores sort from SortStateService under the "project-detail" key', async () => {
    const getSpy = vi.fn().mockReturnValue({ active: 'suite', direction: 'asc' });
    await configureModule({ sortGet: getSpy });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(getSpy).toHaveBeenCalledWith('project-detail');
  });

  it('saves sort to SortStateService under the "project-detail" key on sort change', async () => {
    const saveSpy = vi.fn();
    await configureModule({ sortSave: saveSpy });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    (component as unknown as { sort: MatSort }).sort.sort({
      id: 'suite',
      start: 'asc',
      disableClear: false,
    });
    expect(saveSpy).toHaveBeenCalledWith('project-detail', expect.objectContaining({ active: 'suite' }));
  });

  it('sortingDataAccessor returns suite name and last-run timestamp (null as earliest)', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const ds = fixture.componentInstance.dataSource;
    const desktopRow = ds.data.find((r) => r.name === 'Desktop')!;
    const mobileRow = ds.data.find((r) => r.name === 'Mobile')!;
    expect(ds.sortingDataAccessor(desktopRow, 'suite')).toBe('Desktop');
    expect(ds.sortingDataAccessor(desktopRow, 'latestRun')).toBe(Date.parse('2026-01-01T00:00:00Z'));
    expect(ds.sortingDataAccessor(mobileRow, 'latestRun')).toBe(-1);
  });
});

describe('ProjectDetailComponent search', () => {
  afterEach(() => localStorage.clear());

  it('shows only matching rows when search term matches suite name', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onSearch('desk');
    fixture.detectChanges();
    await fixture.whenStable();
    const rows = component.dataSource.filteredData;
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe('Desktop');
  });

  it('shows no-data row when search term matches nothing', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onSearch('zzznomatch');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(component.dataSource.filteredData.length).toBe(0);
  });
});

describe('ProjectDetailComponent status filter', () => {
  afterEach(() => localStorage.clear());

  it('shows all rows when no status filter is active', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.visibleRows().length).toBe(4);
  });

  it('classifies suites with no runs yet as "pass" for filter purposes', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.detectChanges();
    const names = fixture.componentInstance.visibleRows().map((r) => r.name);
    expect(names).toContain('Desktop');
    expect(names).toContain('Mobile');
    expect(fixture.componentInstance.visibleRows().length).toBe(2);
  });

  it('shows failing rows (including unbaselined ones) when fail filter is active', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('fail');
    fixture.detectChanges();
    const names = fixture.componentInstance.visibleRows().map((r) => r.name);
    expect(names).toContain('Tablet');
    expect(names).toContain('Watch');
    expect(fixture.componentInstance.visibleRows().length).toBe(2);
  });

  it('shows only new rows when new filter is active', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('new');
    fixture.detectChanges();
    const rows = fixture.componentInstance.visibleRows();
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe('Watch');
  });

  it('clears filter when the same status is toggled twice', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentInstance.toggleStatus('pass');
    fixture.componentInstance.toggleStatus('pass');
    fixture.detectChanges();
    expect(fixture.componentInstance.visibleRows().length).toBe(4);
  });
});

describe('ProjectDetailComponent query params', () => {
  afterEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  it('seeds searchTerm, activeStatuses, and sortState from URL query params on init', async () => {
    await configureModule({ queryParams: { q: 'desk', status: 'fail,new', sort: 'suite', dir: 'desc' } });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    expect(component.searchTerm()).toBe('desk');
    expect(component.activeStatuses()).toEqual(new Set(['fail', 'new']));
    expect(component.sortState()).toEqual({ active: 'suite', direction: 'desc' });
  });

  it('updates the URL query params immediately when sort changes', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');
    (fixture.componentInstance as unknown as { sort: MatSort }).sort.sort({
      id: 'suite',
      start: 'asc',
      disableClear: false,
    });
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { sort: 'suite', dir: 'asc' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });

  it('updates the URL query params immediately when a status filter is toggled', async () => {
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
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

  it('debounces search term updates to the URL by ~300ms', async () => {
    vi.useFakeTimers();
    await configureModule({});
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigate');

    fixture.componentInstance.onSearch('desk');
    expect(navigateSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(299);
    expect(navigateSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(navigateSpy).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: { q: 'desk' },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
  });
});

describe('ProjectDetailComponent empty state', () => {
  afterEach(() => localStorage.clear());

  it('shows an empty state when the project has zero suites', async () => {
    const emptyProject: ProjectDetail = { id: 2, name: 'Bare', slug: 'bare', suites: [] };
    await configureModule({ projectDetail: () => of(emptyProject), projectSlug: 'bare' });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No suites yet');
    expect(el.querySelector('table')).toBeNull();
  });
});

describe('ProjectDetailComponent API failure', () => {
  afterEach(() => localStorage.clear());

  it('renders without crashing when api.projectDetail() errors', async () => {
    await configureModule({ projectDetail: () => throwError(() => new Error('network')) });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('shows an error/empty state and no h1 when api.projectDetail() errors', async () => {
    await configureModule({ projectDetail: () => throwError(() => new Error('network')) });
    const fixture = TestBed.createComponent(ProjectDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')).toBeNull();
    expect(el.textContent).toContain('Unable to load this project');
  });
});
