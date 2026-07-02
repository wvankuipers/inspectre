import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { filter, map } from 'rxjs';
import { LoadingService } from '../../services/loading.service';
import { AppToolbarComponent } from '../app-toolbar/app-toolbar.component';
import { PageFooterComponent } from '../page-footer/page-footer.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, AppToolbarComponent, PageFooterComponent, MatProgressBarModule],
  templateUrl: './app-shell.component.html',
  styleUrl: './app-shell.component.scss',
})
export class AppShellComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly loading = inject(LoadingService).loading;

  readonly backLink = toSignal(
    this.router.events.pipe(
      filter(e => e instanceof NavigationEnd),
      map(() => this.route.firstChild?.snapshot?.data?.['backLink'] ?? null),
    ),
    { initialValue: this.route.firstChild?.snapshot?.data?.['backLink'] ?? null as string | null },
  );
}
