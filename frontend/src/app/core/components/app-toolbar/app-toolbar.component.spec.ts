import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { describe, it, expect, beforeEach } from 'vitest';
import { AppToolbarComponent } from './app-toolbar.component';

describe('AppToolbarComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppToolbarComponent],
      providers: [provideNoopAnimations(), provideRouter([])],
    }).compileComponents();
  });

  it('renders the Inspectre wordmark', () => {
    const fixture = TestBed.createComponent(AppToolbarComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.wordmark-name')?.textContent?.trim()).toBe('Inspectre');
    expect(el.querySelector('.wordmark-tag')?.textContent?.trim()).toBe('Visual Regression');
  });

  it('renders brand as div when backLink is null', () => {
    const fixture = TestBed.createComponent(AppToolbarComponent);
    fixture.componentRef.setInput('backLink', null);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('a.brand')).toBeNull();
    expect(el.querySelector('div.brand')).not.toBeNull();
  });

  it('renders brand as anchor with routerLink when backLink is set', () => {
    const fixture = TestBed.createComponent(AppToolbarComponent);
    fixture.componentRef.setInput('backLink', '/projects');
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('a.brand')).not.toBeNull();
    expect(el.querySelector('div.brand')).toBeNull();
  });
});
