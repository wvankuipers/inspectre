import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { RunStats } from '../../models/api';

export type ChipStatus = 'pass' | 'fail' | 'flaky' | 'new';
export interface ChipLink {
  commands: unknown[];
  queryParams?: Record<string, string>;
}
export type ChipLinkFn = (status: ChipStatus) => ChipLink | null;

@Component({
  selector: 'app-run-stats-chips',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './run-stats-chips.component.html',
})
export class RunStatsChipsComponent {
  readonly stats = input.required<RunStats>();
  readonly link = input<ChipLinkFn | undefined>();
}
