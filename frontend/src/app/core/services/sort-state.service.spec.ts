import { TestBed } from '@angular/core/testing';
import { Sort } from '@angular/material/sort';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { SortStateService } from './sort-state.service';

describe('SortStateService', () => {
  let service: SortStateService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(SortStateService);
  });

  afterEach(() => localStorage.clear());

  it('returns default when no entry exists', () => {
    const result = service.get('projects');
    expect(result).toEqual({ active: '', direction: '' });
  });

  it('returns stored sort when a valid entry exists', () => {
    localStorage.setItem(
      'inspectre.sort.projects',
      JSON.stringify({ active: 'project', direction: 'asc' }),
    );
    const result = service.get('projects');
    expect(result).toEqual({ active: 'project', direction: 'asc' });
  });

  it('returns default when stored JSON is corrupted', () => {
    localStorage.setItem('inspectre.sort.projects', 'not-json{{{');
    const result = service.get('projects');
    expect(result).toEqual({ active: '', direction: '' });
  });

  it('save() writes the expected JSON string', () => {
    const sort: Sort = { active: 'name', direction: 'desc' };
    service.save('baselines', sort);
    expect(localStorage.getItem('inspectre.sort.baselines')).toBe(
      JSON.stringify(sort),
    );
  });

  it('save() does not throw when localStorage throws', () => {
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(() =>
      service.save('projects', { active: 'project', direction: 'asc' }),
    ).not.toThrow();
  });
});
