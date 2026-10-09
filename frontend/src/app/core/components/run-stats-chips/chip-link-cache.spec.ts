import { describe, expect, it } from 'vitest';
import { ChipLinkCache } from './chip-link-cache';

describe('ChipLinkCache', () => {
  it('returns the same fn for the same target and mode', () => {
    const cache = new ChipLinkCache();
    expect(cache.get(['/projects', 'a', 'runs', 3])).toBe(cache.get(['/projects', 'a', 'runs', 3]));
  });

  it('returns distinct fns for different targets or modes', () => {
    const cache = new ChipLinkCache();
    expect(cache.get(['/projects', 'a'])).not.toBe(cache.get(['/projects', 'b']));
    expect(cache.get(['/projects', 'a'])).not.toBe(cache.get(['/projects', 'a'], 'none'));
  });

  it('adds status query param for every pill in "all" mode', () => {
    const fn = new ChipLinkCache().get(['/projects', 'a']);
    expect(fn('flaky')).toEqual({ commands: ['/projects', 'a'], queryParams: { status: 'flaky' } });
    expect(fn('pass')?.queryParams).toEqual({ status: 'pass' });
  });

  it('omits the query for flaky in "except-flaky" mode', () => {
    const fn = new ChipLinkCache().get(['/projects', 'a'], 'except-flaky');
    expect(fn('flaky')?.queryParams).toBeUndefined();
    expect(fn('fail')?.queryParams).toEqual({ status: 'fail' });
  });

  it('omits the query for every pill in "none" mode', () => {
    const fn = new ChipLinkCache().get(['/projects', 'a'], 'none');
    expect(fn('new')?.queryParams).toBeUndefined();
  });
});
