import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

export interface BreadcrumbSegment {
  label: string;
  link?: string | string[];
}

@Component({
  selector: 'app-breadcrumb',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './breadcrumb.component.html',
})
export class BreadcrumbComponent {
  readonly segments = input<BreadcrumbSegment[]>([]);
}
