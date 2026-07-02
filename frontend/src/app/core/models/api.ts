// Mirror of the SPA serializers in core/serializers.py.
// Field names match DRF output exactly. If a name diverges, the SPA breaks at
// runtime; TypeScript can't catch wire-format drift at compile time.

export interface Project {
  id: number;
  name: string;
  slug: string;
  suites: SuiteSummary[];
}

export interface SuiteSummary {
  id: number;
  name: string;
  slug: string;
  latest_run: RunSummary | null;
}

export interface SuiteDetail {
  id: number;
  name: string;
  slug: string;
  project_name: string;
  latest_runs: RunSummary[];
  baselines: Baseline[];
}

export interface RunSummary {
  id: number;
  sequential_id: number;
  created_at: string; // ISO-8601 from DRF
  passing: number;
  failing: number;
  unbaselined: number;
}

export interface RunDetail {
  id: number;
  sequential_id: number;
  created_at: string;
  project_name: string;
  tests: TestRow[];
}

export interface TestRow {
  id: number;
  name: string;
  browser: string;
  size: string;
  source_url: string; // empty string when not set
  status: string;
  diff: number;
  // SPA wire format uses `passed`. Legacy Client API uses `pass`. Don't conflate.
  passed: boolean;
  key: string;
  is_baseline_source: boolean; // decisions.md #3 — "new baseline" chip
  fuzz_level: string;
  highlight_colour: string;
  crop_area: string; // empty string when not set
  screenshot_url: string | null;
  baseline_url: string | null;
  diff_url: string | null;
  screenshot_thumb_url: string | null;
  baseline_thumb_url: string | null;
  diff_thumb_url: string | null;
  created_at: string;
}

export interface Baseline {
  id: number;
  name: string;
  browser: string;
  size: string;
  key: string;
  screenshot_url: string | null;
  thumbnail_url: string | null;
  created_at: string;
}
