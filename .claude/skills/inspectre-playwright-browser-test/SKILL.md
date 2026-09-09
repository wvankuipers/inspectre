---
name: inspectre-playwright-browser-test
description: Use to exercise multi-step SPA user flows in a real browser via the Playwright MCP tools — drag interactions, keyboard navigation, filter/sort combinations, and localStorage persistence. Complements inspectre-verify-spa-in-browser, which is a single-screenshot gate.
---

# Inspectre Playwright browser test

`inspectre-verify-spa-in-browser` (Chrome DevTools MCP) is a quick "does it look right"
gate after rebuilding the SPA. Use *this* skill instead when the change needs a scripted,
multi-step interaction to actually prove — not just a screenshot: dragging, keyboard
navigation, a filter+sort combination, or state that must survive a reload.

## Setup

1. Rebuild and start the SPA (and API/worker if the flow touches backend state):
   ```
   docker compose build spa && docker compose up -d spa
   ```
2. `browser_navigate` to `http://localhost:4200`.
3. Prefer `browser_snapshot` (accessibility tree) over screenshots to get stable
   selectors/refs for `browser_click`/`browser_type`/`browser_fill_form` — screenshots are
   for final visual confirmation only, not for locating elements.

## Flows specific to this app

- **`RunDetailComponent` filtering** — `browser_type` into the `SearchFieldComponent`
  (debounced — use `browser_wait_for` on the resulting row count/text, don't assume
  instant), then `browser_click` a status chip filter (All/Pass/Fail/New), and confirm
  both filters compose (row set matches the intersection, not either alone).
- **Sort persistence** — click a sortable column header, `browser_navigate` a reload (or
  revisit the route), and confirm the sort survived — it's persisted to `localStorage`
  under `inspectre.sort.<table-id>` via `SortStateService`. Use `browser_evaluate` to read
  `localStorage.getItem(...)` directly if the visual order alone isn't a strong enough
  assertion.
- **`ImageViewerComponent` navigation** — open the modal via a thumbnail click, then use
  `browser_press_key` for ArrowLeft/ArrowRight (cycle Baseline → Comparison → Diff →
  Compare → Baseline), ArrowUp/ArrowDown (prev/next test), and Escape (close). Confirm
  the shimmer skeleton (`.img-skeleton`/`.img-loaded`) resolves after each navigation via
  `browser_snapshot`, not just visually.
- **Compare-mode drag** — in Compare slot, use `browser_drag` on the divider handle and
  confirm the split position updates; toggle the **vs** button and confirm the right-side
  image switches between Comparison and Diff.
- **Focus-dependent keyboard behavior** — this modal has more than one focusable target
  (the modal body vs. the compare divider handle), and the same key can mean different
  things depending on which has focus. Don't assume "the modal is open" is enough context
  for an ArrowLeft/ArrowRight assertion. After any click/drag, use `browser_snapshot` to
  confirm which element is focused, then press the key, then re-snapshot to confirm which
  effect fired (slot changed vs. divider moved) — never both, unless that's the specific
  behavior under test.
- **Set as baseline** — click "Set as baseline" on a failing test row, and confirm the
  chip flips from fail to pass and the button disappears without a full page reload
  (optimistic update) — check `browser_network_requests` to confirm only
  `POST /api/tests/:id/set-baseline/` fired, not a full refetch.
- **Error/loading states** — use `browser_network_request` to simulate/observe a failed
  API call and confirm `ErrorInterceptor`'s snackbar appears (`error-snack` panel class,
  ~5s) and the route falls back to an empty state rather than crashing.

## Verification

- `browser_console_messages` — zero new console errors after the flow.
- `browser_network_requests` — only the expected calls fired (no duplicate polling, no
  calls to the legacy un-prefixed endpoints from the SPA).
- Take a final `browser_take_screenshot` only as supporting evidence once the scripted
  assertions above already pass — it is not a substitute for them.

Never report the flow verified without having actually driven it through Playwright in
this session — do not infer success from reading the component code.
