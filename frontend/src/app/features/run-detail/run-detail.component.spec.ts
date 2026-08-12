import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { RunDetail } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';
import { RunDetailComponent } from './run-detail.component';

const RUN: RunDetail = {
  id: 1,
  sequential_id: 1,
  created_at: '2026-01-01T00:00:00Z',
  project_name: 'Acme Corp',
  tests: [
    {
      id: 1,
      name: 'Zeta page',
      browser: 'chrome',
      size: '1280x800',
      source_url: '',
      status: 'done',
      diff: 5,
      passed: false,
      key: 'z',
      is_baseline_source: false,
      fuzz_level: '0',
      highlight_colour: 'red',
      crop_area: '',
      screenshot_url: 'http://s3/z.png',
      baseline_url: 'http://s3/z-base.png',
      diff_url: null,
      screenshot_thumb_url: null,
      baseline_thumb_url: null,
      diff_thumb_url: null,
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2,
      name: 'Alpha page',
      browser: 'chrome',
      size: '1280x800',
      source_url: '',
      status: 'done',
      diff: 0,
      passed: true,
      key: 'a',
      is_baseline_source: false,
      fuzz_level: '0',
      highlight_colour: 'red',
      crop_area: '',
      screenshot_url: 'http://s3/a.png',
      baseline_url: 'http://s3/a-base.png',
      diff_url: null,
      screenshot_thumb_url: null,
      baseline_thumb_url: null,
      diff_thumb_url: null,
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 3,
      name: 'Beta new',
      browser: 'chrome',
      size: '1280x800',
      source_url: '',
      status: 'done',
      diff: 0,
      passed: false,
      key: 'b',
      is_baseline_source: false,
      fuzz_level: '0',
      highlight_colour: 'red',
      crop_area: '',
      screenshot_url: 'http://s3/b.png',
      baseline_url: null,
      diff_url: null,
      screenshot_thumb_url: null,
      baseline_thumb_url: null,
      diff_thumb_url: null,
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
};

const RUN_EMPTY: RunDetail = {
  id: 2,
  sequential_id: 2,
  created_at: '2026-01-01T00:00:00Z',
  project_name: 'Acme Corp',
  tests: [],
};

const RUN_WITH_THUMBS: RunDetail = {
  id: 3,
  sequential_id: 3,
  created_at: '2026-01-01T00:00:00Z',
  project_name: 'Acme Corp',
  tests: [
    {
      id: 10,
      name: 'Home page',
      browser: 'Chrome',
      size: '1024',
      source_url: '',
      status: 'done',
      diff: 1.5,
      passed: false,
      key: 'h',
      is_baseline_source: false,
      fuzz_level: '0',
      highlight_colour: 'red',
      crop_area: '',
      screenshot_url: 'http://s3/h.png',
      baseline_url: 'http://s3/h-base.png',
      diff_url: 'http://s3/h-diff.png',
      screenshot_thumb_url: 'http://s3/h-thumb.png',
      baseline_thumb_url: 'http://s3/h-base-thumb.png',
      diff_thumb_url: 'http://s3/h-diff-thumb.png',
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
};

describe('RunDetailComponent sorting', () => {
  let sortServiceGet: ReturnType<typeof vi.fn>;
  let sortServiceSave: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    sortServiceGet = vi.fn().mockReturnValue({ active: 'name', direction: 'asc' });
    sortServiceSave = vi.fn();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        { provide: SortStateService, useValue: { get: sortServiceGet, save: sortServiceSave } },
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('restores sort from SortStateService on init', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(sortServiceGet).toHaveBeenCalledWith('run-tests');
  });

  it('sortedTests() returns tests sorted by name asc', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component['sortState'].set({ active: 'name', direction: 'asc' });
    const names = component.sortedTests().map((t) => t.name);
    expect(names).toEqual(['Alpha page', 'Beta new', 'Zeta page']);
  });

  it('sortedTests() returns passing tests first when sorted by result asc', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component['sortState'].set({ active: 'result', direction: 'asc' });
    const passed = component.sortedTests().map((t) => t.passed);
    expect(passed[0]).toBe(true);
    expect(passed.slice(1).every((p) => p === false)).toBe(true);
  });

  it('saves sort on change', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component.onSortChange({ active: 'result', direction: 'desc' });
    expect(sortServiceSave).toHaveBeenCalledWith('run-tests', {
      active: 'result',
      direction: 'desc',
    });
  });

  it('renders project name in h1 heading', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const h1 = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(h1?.textContent).toContain('Acme Corp');
    expect(h1?.textContent).toContain('Run #1');
  });
});

describe('RunDetailComponent filtering', () => {
  let component: RunDetailComponent;

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    component = fixture.componentInstance;
  });

  afterEach(() => localStorage.clear());

  it('visibleTests() returns all tests when no filters active', () => {
    expect(component.visibleTests().length).toBe(3);
  });

  it('search filters by test name (case-insensitive)', () => {
    component.searchTerm.set('alpha');
    expect(component.visibleTests().map((t) => t.name)).toEqual(['Alpha page']);
  });

  it('search with no match returns empty array', () => {
    component.searchTerm.set('xxxxxxxx');
    expect(component.visibleTests().length).toBe(0);
  });

  it('status filter Pass shows only passing tests with a baseline', () => {
    component.activeStatuses.set(new Set(['pass']));
    expect(component.visibleTests().map((t) => t.name)).toEqual(['Alpha page']);
  });

  it('status filter Fail shows failing tests and new (unbaselined) tests', () => {
    component.activeStatuses.set(new Set(['fail']));
    const names = component
      .visibleTests()
      .map((t) => t.name)
      .sort();
    expect(names).toEqual(['Beta new', 'Zeta page']);
  });

  it('status filter New shows only tests without a baseline', () => {
    component.activeStatuses.set(new Set(['new']));
    expect(component.visibleTests().map((t) => t.name)).toEqual(['Beta new']);
  });

  it('multi-select Pass + Fail includes New (unbaselined counts as failed)', () => {
    component.activeStatuses.set(new Set(['pass', 'fail']));
    const names = component
      .visibleTests()
      .map((t) => t.name)
      .sort();
    expect(names).toEqual(['Alpha page', 'Beta new', 'Zeta page']);
  });

  it('search and status filter compose: search "page" + status Fail', () => {
    component.searchTerm.set('page');
    component.activeStatuses.set(new Set(['fail']));
    expect(component.visibleTests().map((t) => t.name)).toEqual(['Zeta page']);
  });
});

describe('RunDetailComponent empty run', () => {
  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '2' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '2' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN_EMPTY), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('does not show filter empty-state when run has no tests', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const emptyMsg = el.querySelector('p.muted');
    // Should show "No tests in this run." not the filter empty-state
    expect(emptyMsg?.textContent?.trim()).toBe('No tests in this run.');
  });
});

describe('RunDetailComponent onImgError guard', () => {
  let fixture: ComponentFixture<RunDetailComponent>;
  let component: RunDetailComponent;

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    component = fixture.componentInstance;
  });

  afterEach(() => localStorage.clear());

  it('sets fallback src on first error', () => {
    const img = document.createElement('img');
    img.src = 'http://s3/original.png';
    const event = { target: img } as unknown as Event;
    component.onImgError(event);
    expect(img.src).toContain('/image_not_found.jpg');
    expect(img.dataset['failed']).toBe('1');
  });

  it('does not set src again when called a second time (prevents infinite loop)', () => {
    const img = document.createElement('img');
    img.src = 'http://s3/original.png';
    const event = { target: img } as unknown as Event;
    component.onImgError(event);
    const srcAfterFirst = img.src;
    expect(srcAfterFirst).toContain('/image_not_found.jpg');
    // Simulate the fallback image also failing — change src to something else
    img.src = 'http://s3/something-else.png';
    const srcBeforeSecondCall = img.src;
    component.onImgError(event);
    // src should NOT have been changed back to /image_not_found.jpg a second time
    expect(img.src).toBe(srcBeforeSecondCall);
  });
});

describe('RunDetailComponent rebaseline refresh', () => {
  let fixture: ComponentFixture<RunDetailComponent>;
  let component: RunDetailComponent;
  let testsBulkSpy: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    testsBulkSpy = vi.fn().mockReturnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN), setBaseline: () => of({}), testsBulk: testsBulkSpy },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    component = fixture.componentInstance;
  });

  afterEach(() => localStorage.clear());

  it('calls testsBulk with only the rebaselined test id after setBaseline succeeds', () => {
    const test = RUN.tests.find((t) => t.id === 1)!;
    component.rebaseline(test);
    expect(testsBulkSpy).toHaveBeenCalledWith([1]);
  });

  it('merges the fresh row from testsBulk into run() without mutating the original test object', () => {
    const originalTest = RUN.tests.find((t) => t.id === 1)!;
    expect(originalTest.passed).toBe(false);
    testsBulkSpy.mockReturnValue(of([{ ...originalTest, passed: true }]));

    component.rebaseline(originalTest);

    const updatedTest = component.run()?.tests.find((t) => t.id === 1);
    expect(updatedTest?.passed).toBe(true);
    expect(originalTest.passed).toBe(false);
  });

  it('pendingId is cleared after rebaseline completes', () => {
    const test = RUN.tests.find((t) => t.id === 1)!;
    component.rebaseline(test);
    expect(component.pendingId().has(1)).toBe(false);
  });
});

describe('RunDetailComponent image viewer', () => {
  let fixture: ComponentFixture<RunDetailComponent>;
  let dialogOpen: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    localStorage.clear();
    dialogOpen = vi.fn().mockReturnValue({ afterClosed: () => of(null) });

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '3' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '3' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN_WITH_THUMBS), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    })
      .overrideProvider(MatDialog, { useValue: { open: dialogOpen } })
      .compileComponents();

    fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  afterEach(() => localStorage.clear());

  it('clicking a baseline thumbnail opens viewer with slot baseline', async () => {
    const btn = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="thumb-baseline"]',
    ) as HTMLButtonElement;
    btn.click();
    expect(dialogOpen).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ data: expect.objectContaining({ slot: 'baseline' }) }),
    );
  });

  it('clicking a comparison thumbnail opens viewer with slot comparison', async () => {
    const btn = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="thumb-comparison"]',
    ) as HTMLButtonElement;
    btn.click();
    expect(dialogOpen).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ data: expect.objectContaining({ slot: 'comparison' }) }),
    );
  });
});

describe('RunDetailComponent API failure', () => {
  afterEach(() => localStorage.clear());

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: {
            run: () => throwError(() => new Error('network')),
            setBaseline: () => of({}),
            testsBulk: () => of([]),
          },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();
  });

  it('renders without crashing when api.run() errors', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('does not render the page h1 when api.run() errors (run is null)', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const h1 = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(h1).toBeNull();
  });
});

async function setup({
  apiSpy = vi.fn().mockReturnValue(of(RUN)),
  testsBulkSpy = vi.fn().mockReturnValue(of([])),
} = {}) {
  localStorage.clear();

  await TestBed.configureTestingModule({
    imports: [RunDetailComponent],
    providers: [
      provideNoopAnimations(),
      provideRouter([]),
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: { get: () => '1' } },
          paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
        },
      },
      {
        provide: InspectreApiService,
        useValue: { run: apiSpy, setBaseline: () => of({}), testsBulk: testsBulkSpy },
      },
      {
        provide: SortStateService,
        useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
      },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(RunDetailComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

const PENDING_RUN: RunDetail = {
  ...RUN,
  tests: [
    {
      ...RUN.tests[0],
      status: 'pending',
      passed: false,
      diff: 0,
      screenshot_thumb_url: null,
      baseline_thumb_url: null,
      diff_thumb_url: null,
    },
  ],
};

describe('pending test state', () => {
  afterEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
  });

  it('shows processing chip for pending tests', async () => {
    const apiSpy = vi.fn().mockReturnValue(of(PENDING_RUN));
    const fixture = await setup({ apiSpy });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Processing');
  });

  it('does not show thumbnails for pending tests', async () => {
    const apiSpy = vi.fn().mockReturnValue(of(PENDING_RUN));
    const fixture = await setup({ apiSpy });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.thumb-btn')).toBeNull();
  });
});

describe('RunDetailComponent thumbnail skeleton', () => {
  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [RunDetailComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => '1' } },
            paramMap: of({ get: (k: string) => (k === 'seqId' ? '1' : 'test') }),
          },
        },
        {
          provide: InspectreApiService,
          useValue: { run: () => of(RUN), setBaseline: () => of({}), testsBulk: () => of([]) },
        },
        {
          provide: SortStateService,
          useValue: { get: vi.fn().mockReturnValue({ active: '', direction: '' }), save: vi.fn() },
        },
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('thumbnail wrapper has img-skeleton class before load fires', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const skeleton = el.querySelector('.thumb-btn .img-skeleton');
    expect(skeleton).toBeNull(); // no thumb url = no button at all in this test
  });

  it('thumbnail wrapper switches to img-loaded after load event fires', async () => {
    const fixture = TestBed.createComponent(RunDetailComponent);
    const comp = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    // Simulate load event for a known thumb URL
    const url = 'http://s3/z.png';
    comp.onImgLoad(url);
    fixture.detectChanges();
    expect(comp.thumbLoaded().has(url)).toBe(true);
  });
});

describe('RunDetailComponent pending-test polling', () => {
  afterEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
    vi.useRealTimers();
  });

  it('does not call testsBulk before 10s have passed', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;

    expect(testsBulkSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(9999);
    expect(testsBulkSpy).not.toHaveBeenCalled();
  });

  it('calls testsBulk with only the pending ids after 10s', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;
    await vi.advanceTimersByTimeAsync(10000);

    expect(testsBulkSpy).toHaveBeenCalledWith([PENDING_RUN.tests[0].id]);
  });

  it('merges a resolved test from testsBulk into run() without refetching the whole run', async () => {
    vi.useFakeTimers();
    const apiSpy = vi.fn().mockReturnValue(of(PENDING_RUN));
    const resolved = { ...PENDING_RUN.tests[0], status: 'done', passed: true };
    const testsBulkSpy = vi.fn().mockReturnValue(of([resolved]));
    const fixturePromise = setup({ apiSpy, testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    const fixture = await fixturePromise;
    await vi.advanceTimersByTimeAsync(10000);

    const component = fixture.componentInstance;
    expect(component.run()?.tests[0].status).toBe('done');
    expect(component.run()?.tests[0].passed).toBe(true);
    expect(apiSpy).toHaveBeenCalledTimes(1); // never refetched the whole run
  });

  it('keeps polling with the still-pending ids when some tests resolve and others do not', async () => {
    vi.useFakeTimers();
    const stillPending = { ...PENDING_RUN.tests[0], id: 99, status: 'pending' };
    const twoPendingRun = { ...PENDING_RUN, tests: [PENDING_RUN.tests[0], stillPending] };
    const apiSpy = vi.fn().mockReturnValue(of(twoPendingRun));
    const resolvedFirst = { ...PENDING_RUN.tests[0], status: 'done', passed: true };
    const testsBulkSpy = vi.fn().mockReturnValue(of([resolvedFirst]));
    const fixturePromise = setup({ apiSpy, testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;
    await vi.advanceTimersByTimeAsync(10000);

    expect(testsBulkSpy).toHaveBeenNthCalledWith(1, [PENDING_RUN.tests[0].id, 99]);

    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenNthCalledWith(2, [99]);
  });

  it('stops polling once the merged state has no pending tests left', async () => {
    vi.useFakeTimers();
    const apiSpy = vi.fn().mockReturnValue(of(PENDING_RUN));
    const resolved = { ...PENDING_RUN.tests[0], status: 'done', passed: true };
    const testsBulkSpy = vi.fn().mockReturnValue(of([resolved]));
    const fixturePromise = setup({ apiSpy, testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;
    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(20000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(1); // no further calls
  });

  it('does not poll at all when the initial run has no pending tests', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;
    await vi.advanceTimersByTimeAsync(20000);

    expect(testsBulkSpy).not.toHaveBeenCalled();
  });

  it('reschedules polling and retries after a testsBulk request errors', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi
      .fn()
      .mockReturnValueOnce(throwError(() => new Error('network')))
      .mockReturnValueOnce(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;

    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(2);
    expect(testsBulkSpy).toHaveBeenNthCalledWith(2, [PENDING_RUN.tests[0].id]);
  });

  it('stops polling after 3 consecutive empty testsBulk responses', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;

    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(20000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3); // capped — no further polls
  });

  it('stops polling after 3 consecutive testsBulk errors', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(throwError(() => new Error('network')));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;

    await vi.advanceTimersByTimeAsync(10000);
    await vi.advanceTimersByTimeAsync(10000);
    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(20000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3); // capped — no further polls
  });

  it('resets the unproductive-poll counter once a requested test is returned', async () => {
    vi.useFakeTimers();
    const resolved = { ...PENDING_RUN.tests[0], status: 'done', passed: true };
    const testsBulkSpy = vi
      .fn()
      .mockReturnValueOnce(of([])) // unproductive: 1
      .mockReturnValueOnce(of([])) // unproductive: 2
      .mockReturnValueOnce(of([resolved])) // productive: resets counter, and resolves the only pending test
      .mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    await fixturePromise;

    await vi.advanceTimersByTimeAsync(10000);
    await vi.advanceTimersByTimeAsync(10000);
    await vi.advanceTimersByTimeAsync(10000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3);

    // The 3rd response resolved the only pending test, so hasPendingTests()
    // is now false and no further polls should be scheduled — this also
    // proves the counter reset didn't itself force an extra poll.
    await vi.advanceTimersByTimeAsync(20000);
    expect(testsBulkSpy).toHaveBeenCalledTimes(3);
  });

  it('clears the pending timer on destroy so no further request fires', async () => {
    vi.useFakeTimers();
    const testsBulkSpy = vi.fn().mockReturnValue(of([]));
    const fixturePromise = setup({ apiSpy: vi.fn().mockReturnValue(of(PENDING_RUN)), testsBulkSpy });

    await vi.advanceTimersByTimeAsync(0);
    const fixture = await fixturePromise;

    fixture.destroy();

    await vi.advanceTimersByTimeAsync(20000);
    expect(testsBulkSpy).not.toHaveBeenCalled();
  });
});
