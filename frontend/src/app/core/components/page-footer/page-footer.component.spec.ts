import { TestBed } from '@angular/core/testing';
import { describe, it, expect, beforeEach } from 'vitest';
import { PageFooterComponent } from './page-footer.component';

describe('PageFooterComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PageFooterComponent],
    }).compileComponents();
  });

  it('renders a version string with semver', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const versionEl = el.querySelector('.footer-version');
    expect(versionEl?.textContent).toMatch(/v\d+\.\d+\.\d+/);
  });

  it('renders a rendered-at timestamp with date, time, and timezone', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const renderedEl = el.querySelector('.footer-rendered');
    // Timezone abbreviation depends on the runner's locale/TZ (CET, UTC, ...),
    // and en-GB month abbreviations aren't always 3 letters (e.g. "Sept"),
    // so assert the format structure rather than exact lengths/specific zone.
    expect(renderedEl?.textContent).toMatch(
      /rendered \d{1,2} \w{3,4} \d{4}, \d{2}:\d{2} \S+/,
    );
  });

  it('links to the GitHub repo with a safe, labelled external anchor', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const link = el.querySelector('a.footer-repo') as HTMLAnchorElement;
    expect(link).not.toBeNull();
    expect(link.getAttribute('href')).toBe('https://github.com/wvankuipers/inspectre');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('aria-label')).toBe('Inspectre on GitHub');
  });

  it('renders the GitHub mark as a decorative inline svg', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const svg = el.querySelector('a.footer-repo svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
  });
});
