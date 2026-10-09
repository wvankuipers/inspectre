import { ChipLinkFn, ChipStatus } from './run-stats-chips.component';

/** Which pills get a `?status=` query param: all, all but flaky, or none. */
export type ChipQueryMode = 'all' | 'except-flaky' | 'none';

/**
 * Memoizes chip link fns by target. Templates must receive a stable fn identity;
 * a new closure per change-detection pass triggers NG0100.
 */
export class ChipLinkCache {
  private readonly cache = new Map<string, ChipLinkFn>();

  get(commands: unknown[], mode: ChipQueryMode = 'all'): ChipLinkFn {
    const key = `${mode}|${commands.join('/')}`;
    let fn = this.cache.get(key);
    if (!fn) {
      fn = (status: ChipStatus) => ({
        commands,
        queryParams:
          mode === 'none' || (mode === 'except-flaky' && status === 'flaky') ? undefined : { status },
      });
      this.cache.set(key, fn);
    }
    return fn;
  }
}
