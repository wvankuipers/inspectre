import { Injectable } from '@angular/core';
import { Sort } from '@angular/material/sort';

const DEFAULT: Sort = { active: '', direction: '' };

@Injectable({ providedIn: 'root' })
export class SortStateService {
  get(tableKey: string): Sort {
    try {
      const raw = localStorage.getItem(`inspectre.sort.${tableKey}`);
      return raw ? (JSON.parse(raw) as Sort) : DEFAULT;
    } catch {
      return DEFAULT;
    }
  }

  save(tableKey: string, sort: Sort): void {
    try {
      localStorage.setItem(`inspectre.sort.${tableKey}`, JSON.stringify(sort));
    } catch {
      // localStorage unavailable — sort works in-session, not persisted
    }
  }
}
