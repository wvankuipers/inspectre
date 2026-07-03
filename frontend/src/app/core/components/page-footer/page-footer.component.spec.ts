import { TestBed } from '@angular/core/testing';
import { describe, it, expect, beforeEach } from 'vitest';
import { PageFooterComponent } from './page-footer.component';

describe('PageFooterComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PageFooterComponent],
    }).compileComponents();
  });

  it('renders a version string with semver and sha', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const versionEl = el.querySelector('.footer-version');
    expect(versionEl?.textContent).toMatch(/v\d+\.\d+\.\d+/);
    expect(versionEl?.textContent).toContain(fixture.componentInstance.sha);
  });

  it('renders a rendered-at timestamp with date, time, and timezone', () => {
    const fixture = TestBed.createComponent(PageFooterComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const renderedEl = el.querySelector('.footer-rendered');
    // Timezone abbreviation depends on the runner's locale/TZ (CET, UTC, ...),
    // so assert the format structure rather than a specific zone.
    expect(renderedEl?.textContent).toMatch(
      /rendered \d{1,2} \w{3} \d{4}, \d{2}:\d{2} \S+/,
    );
  });
});
