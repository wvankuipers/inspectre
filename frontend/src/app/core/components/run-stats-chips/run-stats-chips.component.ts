import { Component, input } from '@angular/core';
import { RunSummary } from '../../models/api';

@Component({
  selector: 'app-run-stats-chips',
  standalone: true,
  imports: [],
  templateUrl: './run-stats-chips.component.html',
})
export class RunStatsChipsComponent {
  readonly stats = input.required<RunSummary>();
}
