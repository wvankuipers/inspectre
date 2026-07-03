import { Routes } from '@angular/router';
import { AppShellComponent } from './core/components/app-shell/app-shell.component';

export const routes: Routes = [
  {
    path: '',
    component: AppShellComponent,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'projects' },
      {
        path: 'projects',
        loadComponent: () =>
          import('./features/projects-list/projects-list.component').then(
            (m) => m.ProjectsListComponent,
          ),
        data: {},
      },
      {
        path: 'projects/:projectSlug/suites/:suiteSlug',
        loadComponent: () =>
          import('./features/suite-detail/suite-detail.component').then(
            (m) => m.SuiteDetailComponent,
          ),
        data: { backLink: '/projects' },
      },
      {
        path: 'projects/:projectSlug/suites/:suiteSlug/runs/:seqId',
        loadComponent: () =>
          import('./features/run-detail/run-detail.component').then(
            (m) => m.RunDetailComponent,
          ),
        data: { backLink: '/projects' },
      },
      { path: '**', redirectTo: 'projects' },
    ],
  },
];
