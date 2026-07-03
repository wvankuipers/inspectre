import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { BreadcrumbComponent } from './breadcrumb.component';

describe('BreadcrumbComponent', () => {
  let fixture: ComponentFixture<BreadcrumbComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BreadcrumbComponent],
      providers: [provideRouter([])],
    }).compileComponents();
    fixture = TestBed.createComponent(BreadcrumbComponent);
  });

  it('renders all segment labels', async () => {
    fixture.componentRef.setInput('segments', [
      { label: 'Projects', link: '/projects' },
      { label: 'my-suite' },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Projects');
    expect(el.textContent).toContain('my-suite');
  });

  it('renders links for segments with a link value', async () => {
    fixture.componentRef.setInput('segments', [
      { label: 'Projects', link: '/projects' },
      { label: 'Current' },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();
    const links = (fixture.nativeElement as HTMLElement).querySelectorAll('a');
    expect(links.length).toBe(1);
    expect(links[0].getAttribute('href')).toBe('/projects');
  });

  it('renders the last segment without a link', async () => {
    fixture.componentRef.setInput('segments', [
      { label: 'Projects', link: '/projects' },
      { label: 'Current' },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const nonSeparatorSpans = Array.from(el.querySelectorAll('nav > span')).filter(
      s => s.textContent?.trim() !== '›',
    );
    expect(nonSeparatorSpans[nonSeparatorSpans.length - 1].textContent?.trim()).toBe('Current');
  });

  it('renders › separators between segments', async () => {
    fixture.componentRef.setInput('segments', [
      { label: 'A', link: '/a' },
      { label: 'B', link: '/b' },
      { label: 'C' },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const separators = Array.from(el.querySelectorAll('nav > span')).filter(
      s => s.textContent?.trim() === '›',
    );
    expect(separators.length).toBe(2);
  });
});
