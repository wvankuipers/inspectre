import { Component, ElementRef, ViewChild, input, model } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

@Component({
  selector: 'app-search-field',
  standalone: true,
  imports: [MatFormFieldModule, MatInputModule, MatButtonModule],
  templateUrl: './search-field.component.html',
  styleUrl: './search-field.component.scss',
})
export class SearchFieldComponent {
  readonly label = input<string>('Search…');
  readonly value = model<string>('');

  @ViewChild('inputEl') private inputEl!: ElementRef<HTMLInputElement>;

  onInput(event: Event): void {
    this.value.set((event.target as HTMLInputElement).value);
  }

  clear(): void {
    this.value.set('');
    const el = this.inputEl.nativeElement;
    el.value = '';
    el.focus();
  }
}
