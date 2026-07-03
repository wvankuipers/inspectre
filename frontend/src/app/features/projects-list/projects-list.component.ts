import { DatePipe } from '@angular/common';
import {
  AfterViewInit,
  Component,
  DestroyRef,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatSort, MatSortModule, Sort } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';

import { InspectreApiService } from '../../core/api/inspectre-api.service';
import { RunStatsChipsComponent } from '../../core/components/run-stats-chips/run-stats-chips.component';
import { SearchFieldComponent } from '../../core/components/search-field/search-field.component';
import { Project, SuiteSummary } from '../../core/models/api';
import { SortStateService } from '../../core/services/sort-state.service';

interface Row {
  project: Project;
  suite: SuiteSummary;
}

@Component({
  selector: 'app-projects-list',
  standalone: true,
  imports: [
    DatePipe,
    RouterLink,
    MatButtonModule,
    MatSortModule,
    MatTableModule,
    SearchFieldComponent,
    RunStatsChipsComponent,
  ],
  templateUrl: './projects-list.component.html',
  styleUrl: './projects-list.component.scss',
})
export class ProjectsListComponent implements AfterViewInit {
  private api = inject(InspectreApiService);
  private sortService = inject(SortStateService);
  private destroyRef = inject(DestroyRef);

  @ViewChild(MatSort) private sort!: MatSort;

  readonly columns = ['project', 'suite', 'latestRun', 'status'];
  readonly sortState = signal<Sort>(this.sortService.get('projects'));
  readonly searchTerm = signal<string>('');
  readonly activeStatuses = signal<Set<'pass' | 'fail' | 'new'>>(new Set());
  readonly dataSource = new MatTableDataSource<Row>();

  private projects = toSignal(
    this.api.projects().pipe(
      takeUntilDestroyed(),
      catchError(() => of<Project[]>([])),
    ),
    { initialValue: undefined },
  );

  readonly loading = computed(() => this.projects() === undefined);

  readonly rows = computed<Row[]>(() => {
    const projects = this.projects() ?? [];
    return projects.flatMap((project) => project.suites.map((suite) => ({ project, suite })));
  });

  readonly visibleRows = computed<Row[]>(() => {
    const statuses = this.activeStatuses();
    if (statuses.size === 0) return this.rows();
    return this.rows().filter((row) => {
      const run = row.suite.latest_run;
      if (!run) return false;
      if (run.failing > 0) return statuses.has('fail');
      if (run.unbaselined > 0) return statuses.has('new');
      return statuses.has('pass');
    });
  });

  constructor() {
    this.dataSource.filterPredicate = (row: Row, filter: string) =>
      row.project.name.toLowerCase().includes(filter) ||
      row.suite.name.toLowerCase().includes(filter);

    this.dataSource.sortingDataAccessor = (row: Row, sortHeaderId: string): string | number => {
      switch (sortHeaderId) {
        case 'project':
          return row.project.name;
        case 'suite':
          return row.suite.name;
        case 'latestRun':
          return row.suite.latest_run?.sequential_id ?? -1;
        default:
          return '';
      }
    };

    effect(() => {
      this.dataSource.data = this.visibleRows();
    });
  }

  ngAfterViewInit(): void {
    this.dataSource.sort = this.sort;
    const saved = this.sortState();
    if (saved.active) {
      this.sort?.sort({
        id: saved.active,
        start: saved.direction as 'asc' | 'desc',
        disableClear: false,
      });
    }
    this.sort?.sortChange.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((sort: Sort) => {
      this.sortState.set(sort);
      this.sortService.save('projects', sort);
    });
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
    this.dataSource.filter = value.trim().toLowerCase();
  }

  toggleStatus(status: 'pass' | 'fail' | 'new'): void {
    this.activeStatuses.update((currentStatuses) => {
      const next = new Set(currentStatuses);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
      }
      return next;
    });
  }
}
