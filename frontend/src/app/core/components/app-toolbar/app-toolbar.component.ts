import { NgTemplateOutlet } from '@angular/common';
import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';

@Component({
  selector: 'app-toolbar',
  standalone: true,
  imports: [NgTemplateOutlet, RouterLink, MatToolbarModule],
  templateUrl: './app-toolbar.component.html',
  styleUrl: './app-toolbar.component.scss',
})
export class AppToolbarComponent {
  readonly backLink = input<string | null>(null);
}
