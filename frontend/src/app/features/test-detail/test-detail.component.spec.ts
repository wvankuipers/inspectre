import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { TestHistory } from '../../core/models/api';
import { TestDetailComponent } from './test-detail.component';

const HISTORY: TestHistory = {
  key: 'home-page-chrome-1280x800',
  name: 'Home page',
  browser: 'chrome',
  size: '1280x800',
  project_name: 'Acme Corp',
  suite_slug: 'main-suite',
  runs: [
    {
      id: 1,
      run_id: 10,
      run_sequential_id: 1,
      run_created_at: '2026-01-01T00:00:00Z',
      original_passed: false,
      is_new_baseline: true,
      status: 'done',
      screenshot_thumb_url: 'http://s3/thumb1.png',
    },
    {
      id: 2,
      run_id: 11,
      run_sequential_id: 2,
      run_created_at: '2026-01-02T00:00:00Z',
      original_passed: true,
      is_new_baseline: false,
      status: 'done',
      screenshot_thumb_url: 'http://s3/thumb2.png',
    },
    {
      id: 3,
      run_id: 12,
      run_sequential_id: 3,
      run_created_at: '2026-01-03T00:00:00Z',
      original_passed: false,
      is_new_baseline: false,
      status: 'done',
      screenshot_thumb_url: null,
    },
    {
      id: 4,
      run_id: 13,
      run_sequential_id: 4,
      run_created_at: '2026-01-04T00:00:00Z',
      original_passed: null,
      is_new_baseline: null,
      status: 'pending',
      screenshot_thumb_url: null,
    },
  ],
};

async function setup({
  apiSpy = vi.fn().mockReturnValue(of(HISTORY)),
  key = 'home-page-chrome-1280x800',
} = {}) {
  await TestBed.configureTestingModule({
    imports: [TestDetailComponent],
    providers: [
      provideNoopAnimations(),
      provideRouter([]),
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: { get: () => key } },
          paramMap: of({
            get: (k: string) => {
              if (k === 'projectSlug') return 'acme-corp';
              if (k === 'suiteSlug') return 'main-suite';
              if (k === 'key') return key;
              return null;
            },
          }),
        },
      },
      { provide: InspectreApiService, useValue: { testHistory: apiSpy } },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(TestDetailComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

describe('TestDetailComponent happy path', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders the test name and browser/size in the header', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const h1 = el.querySelector('h1');
    expect(h1?.textContent).toContain('Home page');
    expect(el.textContent).toContain('chrome · 1280x800');
  });

  it('renders one row per history entry', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    expect(rows.length).toBe(HISTORY.runs.length);
  });

  it('renders a routerLink to the run for each row', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const links = Array.from(el.querySelectorAll('tbody tr a')) as HTMLAnchorElement[];
    expect(links[0].textContent).toContain('#1');
    expect(links[1].textContent).toContain('#2');
  });

  it('renders the formatted date for each row', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    // 'medium' date pipe format renders month name; just assert year present per row.
    const dateCells = el.querySelectorAll('tbody tr td:nth-child(2)');
    expect(dateCells[0].textContent).toContain('2026');
  });

  it('renders a thumbnail image when screenshot_thumb_url is present', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    const img = rows[0].querySelector('img');
    expect(img?.getAttribute('src')).toBe('http://s3/thumb1.png');
  });

  it('renders a dash placeholder when screenshot_thumb_url is null', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    // Row 3 (index 2) has screenshot_thumb_url: null
    expect(rows[2].querySelector('img')).toBeNull();
    expect(rows[2].textContent).toContain('—');
  });
});

describe('TestDetailComponent chip precedence', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('shows "Processing…" chip when status is pending, regardless of other flags', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    // Row 4 (index 3) has status: 'pending'
    expect(rows[3].querySelector('.chip-none')?.textContent).toContain('Processing');
    expect(rows[3].querySelector('.chip-new')).toBeNull();
    expect(rows[3].querySelector('.chip-pass')).toBeNull();
    expect(rows[3].querySelector('.chip-fail')).toBeNull();
  });

  it('shows "Processing…" chip when status is processing', async () => {
    const processingHistory: TestHistory = {
      ...HISTORY,
      runs: [{ ...HISTORY.runs[0], status: 'processing' }],
    };
    const fixture = await setup({ apiSpy: vi.fn().mockReturnValue(of(processingHistory)) });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.chip-none')?.textContent).toContain('Processing');
  });

  it('shows only the "New" chip when is_new_baseline is true, even though original_passed is false', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    // Row 1 (index 0): is_new_baseline: true, original_passed: false
    expect(rows[0].querySelector('.chip-new')?.textContent).toContain('New');
    expect(rows[0].querySelector('.chip-pass')).toBeNull();
    expect(rows[0].querySelector('.chip-fail')).toBeNull();
  });

  it('shows a "Pass" chip using original_passed when not new baseline and not pending', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    // Row 2 (index 1): original_passed: true, is_new_baseline: false
    expect(rows[1].querySelector('.chip-pass')?.textContent).toContain('Pass');
    expect(rows[1].querySelector('.chip-new')).toBeNull();
    expect(rows[1].querySelector('.chip-fail')).toBeNull();
  });

  it('shows a "Fail" chip using original_passed when not new baseline and not pending', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('tbody tr');
    // Row 3 (index 2): original_passed: false, is_new_baseline: false
    expect(rows[2].querySelector('.chip-fail')?.textContent).toContain('Fail');
    expect(rows[2].querySelector('.chip-new')).toBeNull();
    expect(rows[2].querySelector('.chip-pass')).toBeNull();
  });

  it('still shows "Fail" for a row that failed originally even if it was later promoted to baseline elsewhere (original_passed is immutable)', async () => {
    // Simulates a row where original_passed stayed false despite the test's
    // current baseline status being irrelevant to this historical record.
    const promotedHistory: TestHistory = {
      ...HISTORY,
      runs: [
        {
          id: 5,
          run_id: 14,
          run_sequential_id: 5,
          run_created_at: '2026-01-05T00:00:00Z',
          original_passed: false,
          is_new_baseline: false,
          status: 'done',
          screenshot_thumb_url: null,
        },
      ],
    };
    const fixture = await setup({ apiSpy: vi.fn().mockReturnValue(of(promotedHistory)) });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.chip-fail')?.textContent).toContain('Fail');
  });
});

describe('TestDetailComponent error state', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders the error message when the API call fails', async () => {
    const fixture = await setup({
      apiSpy: vi.fn().mockReturnValue(throwError(() => new Error('network'))),
    });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.load-error')?.textContent).toContain(
      'Failed to load test history',
    );
  });

  it('does not render the header when the API call fails', async () => {
    const fixture = await setup({
      apiSpy: vi.fn().mockReturnValue(throwError(() => new Error('network'))),
    });
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')).toBeNull();
  });
});

describe('TestDetailComponent breadcrumb', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders Projects, project name, suite, and test name segments', async () => {
    const fixture = await setup();
    const el = fixture.nativeElement as HTMLElement;
    const nav = el.querySelector('nav.breadcrumb');
    expect(nav?.textContent).toContain('Projects');
    expect(nav?.textContent).toContain('Acme Corp');
    expect(nav?.textContent).toContain('main-suite');
    expect(nav?.textContent).toContain('Home page');
  });
});
