import { Component } from '@angular/core';
import { BUILD_SHA, BUILD_VERSION } from '../../../build-info';

@Component({
  selector: 'app-page-footer',
  standalone: true,
  templateUrl: './page-footer.component.html',
  styleUrl: './page-footer.component.scss',
})
export class PageFooterComponent {
  readonly version = BUILD_VERSION;
  readonly sha = BUILD_SHA;
  readonly renderedAt = new Date().toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}
