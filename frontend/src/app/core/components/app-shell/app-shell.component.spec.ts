import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { LoadingService } from '../../services/loading.service';
import { AppShellComponent } from './app-shell.component';

describe('AppShellComponent', () => {
  let routerEvents$: Subject<unknown>;

  const setup = async (childData: Record<string, unknown> = {}, firstChildOverride?: unknown) => {
    routerEvents$ = new Subject();
    const firstChild =
      firstChildOverride !== undefined
        ? firstChildOverride
        : Object.keys(childData).length
          ? { snapshot: { data: childData } }
          : null;
    await TestBed.configureTestingModule({
      imports: [AppShellComponent],
      providers: [
        provideNoopAnimations(),
        {
          provide: Router,
          useValue: { events: routerEvents$.asObservable() },
        },
        {
          provide: ActivatedRoute,
          useValue: { firstChild },
        },
      ],
    }).compileComponents();
    return TestBed.createComponent(AppShellComponent);
  };

  it('backLink() is null when child route has no data', async () => {
    const fixture = await setup();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.backLink()).toBeNull();
  });

  it('backLink() is null when firstChild exists but snapshot is undefined', async () => {
    const fixture = await setup({}, { snapshot: undefined });
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.backLink()).toBeNull();
  });

  it('backLink() reads value from first child route data', async () => {
    const fixture = await setup({ backLink: '/projects' });
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.componentInstance.backLink()).toBe('/projects');
  });

  it('shows progress bar when LoadingService.loading is true', async () => {
    const fixture = await setup();
    TestBed.inject(LoadingService).increment();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('mat-progress-bar')).not.toBeNull();
  });

  it('hides progress bar when LoadingService.loading is false', async () => {
    const fixture = await setup();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('mat-progress-bar')).toBeNull();
  });
});
