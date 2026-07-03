import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { describe, it, expect, beforeEach } from 'vitest';
import { SearchFieldComponent } from './search-field.component';

describe('SearchFieldComponent', () => {
  let fixture: ComponentFixture<SearchFieldComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SearchFieldComponent],
      providers: [provideNoopAnimations()],
    }).compileComponents();
    fixture = TestBed.createComponent(SearchFieldComponent);
  });

  it('renders the label input as placeholder text', async () => {
    fixture.componentRef.setInput('label', 'Search by name');
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('input')?.placeholder).toBe('Search by name');
  });

  it('emits valueChange with the typed string on input event', async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    let emitted: string | undefined;
    fixture.componentInstance.value.subscribe((v: string) => (emitted = v));
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    input.value = 'hello';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(emitted).toBe('hello');
  });

  it('clear button is absent when value is empty', async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    const clearBtn = fixture.nativeElement.querySelector('[aria-label="Clear"]');
    expect(clearBtn).toBeNull();
  });

  it('clear button is present when value is non-empty', async () => {
    fixture.componentRef.setInput('value', 'foo');
    fixture.detectChanges();
    await fixture.whenStable();
    const clearBtn = fixture.nativeElement.querySelector('[aria-label="Clear"]');
    expect(clearBtn).not.toBeNull();
  });

  it('clicking clear button sets value to empty string and emits valueChange', async () => {
    fixture.componentRef.setInput('value', 'foo');
    fixture.detectChanges();
    await fixture.whenStable();
    let emitted: string | undefined;
    fixture.componentInstance.value.subscribe((v: string) => (emitted = v));
    const clearBtn = fixture.nativeElement.querySelector('[aria-label="Clear"]') as HTMLButtonElement;
    clearBtn.click();
    fixture.detectChanges();
    expect(emitted).toBe('');
  });
});
