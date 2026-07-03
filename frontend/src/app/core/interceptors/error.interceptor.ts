import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { catchError, throwError } from 'rxjs';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const snackBar = inject(MatSnackBar);

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      const message =
        error.status === 0
          ? 'Cannot reach Inspectre. Check your connection.'
          : `${error.status} ${error.statusText || 'error'}`;

      snackBar.open(message, 'Dismiss', {
        duration: 5000,
        panelClass: 'error-snack',
      });

      return throwError(() => error);
    }),
  );
};
