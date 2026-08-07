# HTTP API

There is **no authentication** on any endpoint. CSRF protection is not required on the legacy endpoints since DRF's `AllowAny` permission class is used without session authentication.

## Route table

| Method  | Path                                                  | Controller#action     | Auth | CSRF | Notes |
| ------- | ----------------------------------------------------- | --------------------- | ---- | ---- | ----- |
| GET     | `/`                                                   | redirect → `/projects`| —    | —    |       |
| GET     | `/projects`                                           | `projects#index`      | none | n/a  | HTML only |
| GET     | `/projects/:project_slug/suites/:slug`                | `suites#show`         | none | n/a  | HTML only |
| GET     | `/projects/:project_slug/suites/:suite_slug/runs/:sequential_id` | `runs#show` | none | exempt | HTML or JSON |
| GET     | `/runs/new`                                           | `runs#new`            | none | exempt | Tiny HTML form |
| POST    | `/runs`                                               | `runs#create`         | none | exempt | JSON only |
| GET     | `/tests/new`                                          | `tests#new`           | none | exempt | Tiny HTML form (auto-creates a "Test Project / Test Suite / run") |
| POST    | `/tests`                                              | `tests#create`        | none | exempt | JSON only |
| PATCH/PUT | `/tests/:id`                                        | `tests#update`        | none | exempt | "Set as baseline" — HTML redirect or AJAX |
| GET     | `/baselines/:key`                                     | `baselines#show`      | none | n/a  | PNG (default) or JSON |
| any     | `/admin/*`                                            | Django admin          | none | n/a  | Full CRUD UI |
| any     | `/media/:job/:name`                                   | Dragonfly middleware  | none | n/a  | Image fetch (signed Dragonfly URLs); only used when datastore is local files |

## Endpoints in detail

### `POST /runs`

Creates (or reuses) a project + suite, then creates a fresh run.

Request (form-encoded or JSON; `wrap_parameters` is on for JSON):

```http
POST /runs
Content-Type: application/x-www-form-urlencoded

project=Acme%20Site&suite=Desktop
```

Behaviour: `Project.find_or_create_by(name:)` then `suite.find_or_create_by(name:)` then `suite.runs.create`. Note this is `find_or_create_by`, so submitting "Acme Site " (trailing space) creates a different project. There is no slug-based lookup at ingest.

Response (200 OK, application/json):

```json
{
  "id": 42,
  "suite_id": 7,
  "sequential_id": 12,
  "created_at": "2026-06-12T10:00:00.000Z",
  "updated_at": "2026-06-12T10:00:00.000Z",
  "url": "/projects/acme-site/suites/desktop/runs/12"
}
```

The `url` field is injected by `Run#as_json`. Clients should keep `id` (raw run id) for posting tests, or `sequential_id` for human-friendly URLs.

### `POST /tests`

Submits a screenshot for comparison. Returns immediately (~50 ms) with `status: "pending"`. The ImageMagick pipeline runs asynchronously in a Celery worker.

Request (multipart/form-data):

```http
POST /tests
Content-Type: multipart/form-data; boundary=…

test[run_id]=42
test[name]=Homepage
test[browser]=Chrome
test[size]=1024
test[screenshot]=@homepage.png         # required
test[crop_area]=640x480+50+100         # optional, ImageMagick crop spec
test[fuzz_level]=30%                   # optional, default "30%"
test[highlight_colour]=ff0000          # optional, default "ff0000" (no leading #)
test[source_url]=https://example.com/  # optional
```

Server flow:

1. Validate params (`name`, `browser`, `size`, `run_id`, `screenshot` required).
2. `Test.objects.create(…)` — `status` defaults to `"pending"`; `passed`, `diff`, and image URL fields left null.
3. Stage the uploaded file to S3 at `screenshots/staging/<id>/upload.png`.
4. Enqueue `process_test.delay(test_id, staging_key)`.
5. Return `LegacyTestSerializer(test)` immediately.

The Celery worker then: sets `status="processing"`, runs `ScreenshotComparison` (see [image-diffing.md](image-diffing.md)), sets `status="done"` with all fields populated (or `status="failed"` on error), and deletes the staging file.

Response (200 OK — pending, image fields null):

```json
{
  "id": 1234,
  "name": "Homepage",
  "browser": "Chrome",
  "size": "1024",
  "run_id": 42,
  "status": "pending",
  "diff": 0,
  "pass": false,
  "screenshot_uid": null,
  "screenshot_baseline_uid": null,
  "screenshot_diff_uid": null,
  "key": "acme-site-desktop-homepage-chrome-1024",
  "source_url": null,
  "fuzz_level": "30%",
  "highlight_colour": "ff0000",
  "crop_area": null,
  "created_at": "...",
  "updated_at": "...",
  "url": "/projects/acme-site/suites/desktop/runs/12#test_1234",
  "is_new_baseline": null
}
```

Once the worker completes, `GET /tests/:id/status` returns the same shape with all fields populated and `status: "done"`.

Errors:
- Missing/invalid `run_id` → 404.
- Missing `screenshot` → 400.
- Worker pipeline failure → `status` set to `"failed"` (visible via poll endpoint).

### `GET /tests/:id/status`

Polling endpoint for async test completion. Returns the same shape as `POST /tests`. CI clients poll this every second after a `POST /tests` until `status` is `"done"` or `"failed"`.

```http
GET /tests/1234/status
```

Response — same JSON shape as `POST /tests`. When `status == "done"` all fields are fully populated:

```json
{
  "id": 1234,
  "status": "done",
  "pass": true,
  "diff": 0.04,
  "screenshot_uid": "http://localhost:9000/inspectre-screenshots/screenshots/1234/original.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=...&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=...",
  "screenshot_baseline_uid": "http://localhost:9000/inspectre-screenshots/screenshots/1234/baseline.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=...&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=...",
  "screenshot_diff_uid": "http://localhost:9000/inspectre-screenshots/screenshots/1234/diff.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=...&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=...",
  "is_new_baseline": true,
  ...
}
```

The bucket is private, so these are presigned URLs with a 24-hour expiry — the query string (and therefore the whole URL) differs between requests for the same object, so clients should treat it as a transient signed link, not a stable identifier to cache or compare.

`is_new_baseline` — `true` if this submission established a Baseline that did not previously exist for the key (self-baselined for the first time). Surfaced as a chip in the SPA ([ui.md](ui.md)).

### `PATCH /tests/:id` ("Set as baseline")

Used by the UI when a human accepts a previously-failing test as the new baseline.

Request:

```http
PATCH /tests/1234
test[baseline]=true
```

Behaviour:
- If `test[baseline] == 'true'`, promotes the test: sets `passed = True`, saves, and upserts the Baseline row with this test's screenshot.
- Any other value is a no-op; the test record is returned unchanged.

Note: the view only acts on `test[baseline]=true`. The SPA uses `POST /api/tests/<id>/set-baseline/` instead (same underlying logic).

### `GET /baselines/:key.png` and `GET /baselines/:key.json`

Public read of a baseline by its key. The extension selects the response format:

- `/baselines/:key.png` → streams the screenshot binary inline (`image/png`).
- `/baselines/:key.json` → returns the Baseline record as JSON.

404 if no Baseline matches the key.

### `GET /projects/:project_slug/suites/:suite_slug/runs/:sequential_id`

The Run page. Supports HTML (default) and JSON.

JSON response includes the run plus its tests:

```json
{
  "id": 42,
  "suite_id": 7,
  "sequential_id": 12,
  "created_at": "...",
  "updated_at": "...",
  "url": "/projects/acme-site/suites/desktop/runs/12",
  "tests": [ { /* full test record */ }, ... ]
}
```

HTML response respects query-string filters: `?name=…`, `?browser=…`, `?size=…`, `?status=pass|fail`. See [`TestFilters`](data-model.md#in-memory--non-persisted-classes).

### `GET /runs/new` and `GET /tests/new`

Tiny built-in forms for hand-testing. **`/tests/new` has a side-effect**: every render of the page calls `Project.find_or_create_by(name: 'Test Project')`, `suite.find_or_create_by(name: 'Test Suite')`, and `suite.runs.create`. So just opening the form creates a new run. (Worth dropping in the rebuild.)

### `/admin/*`

Full CRUD over Project / Suite / Run / Test / Baseline. See [admin.md](admin.md).

### Dragonfly `/media/:job/:name`

When the datastore is local files, screenshots are served via Dragonfly's middleware at `/media/<signed_job>/<filename>`. URLs are generated by `screenshot.url` calls. With the S3 datastore, screenshot URLs point directly at S3.

## What clients are expected to do

The API is consumed by CI clients via plain HTTP. The two-step protocol is:

1. `POST /runs` → save `run.id` (the raw integer, not sequential_id).
2. For each screenshot: `POST /tests` with that `run_id` and the file. Returns `status: "pending"`.
3. Poll `GET /tests/:id/status` every second until `status == "done"` or `"failed"`.

Clients have no other obligations — Spectre handles baselining server-side.

## Python/DRF rebuild notes

- Reproduce `POST /runs`, `POST /tests`, `PATCH /tests/<id>`, `GET /baselines/<key>` exactly. **API field names and response shapes are frozen** — keep them byte-for-byte where possible.
- Use DRF generic views or function views; ModelViewSet is overkill since only a subset of CRUD is exposed.
- `POST /tests` stages the file to S3 and enqueues a Celery task immediately. The view returns `status: "pending"` without waiting for the pipeline. The worker sets `status: "done"` when complete.
- Skip CSRF on the API endpoints (DRF's default `SessionAuthentication` only enforces CSRF for cookie-based requests; if you don't add session auth at all, CSRF is moot).
- **Legacy URLs are preserved** ([decisions.md](decisions.md) #7). `POST /runs`, `POST /tests`, `PATCH /tests/:id`, and `GET /baselines/:key` keep their un-prefixed paths and field shapes so existing CI clients keep working without changes. New SPA-only endpoints sit under `/api/` to avoid colliding with the legacy surface.
- Frontend (Angular) consumes:
  - `GET /api/projects/` (list)
  - `GET /api/projects/<slug>/suites/<slug>/` (suite detail w/ recent runs + baselines)
  - `GET /api/projects/<slug>/suites/<slug>/runs/<seq_id>/` (run detail w/ tests)
  - `POST /api/tests/<id>/set-baseline/` (JSON, empty body) is the SPA-preferred shape — idiomatic for Angular's `HttpClient`. Legacy `PATCH /tests/:id` with form-encoded `test[baseline]=true` is kept for CI client compatibility; both endpoints share the same handler.
  - `GET /api/baselines/<key>/` (JSON metadata). The legacy `GET /baselines/<key>.png` keeps streaming the PNG.

## URL routing skeleton

```python
# spectre/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # /admin/ — Django Admin, single shared is_staff login (admin.md)
    path('admin/', admin.site.urls),

    # /api/ — SPA-internal endpoints (versioned implicitly by being SPA-only)
    path('api/', include('core.urls.spa')),

    # Un-prefixed legacy endpoints — frozen for CI client compatibility
    # (decisions.md #7). Order matters: legacy routes must not shadow /api/.
    path('', include('core.urls.legacy')),
]
```

```python
# core/urls/spa.py — SPA-internal API
from django.urls import path
from core.views import api as v

urlpatterns = [
    path('projects/',                                          v.projects_list),
    path('projects/<slug:project>/suites/<slug:suite>/',       v.suite_detail),
    path('projects/<slug:project>/suites/<slug:suite>/runs/<int:seq>/', v.run_detail),
    path('tests/<int:pk>/set-baseline/',                       v.set_baseline),  # POST, JSON
    path('baselines/<str:key>/',                               v.baseline_detail),  # JSON
]
```

```python
# core/urls/legacy.py — frozen contract; do not add fields, do not rename
from django.urls import path, re_path
from core.views import legacy as v

urlpatterns = [
    path('runs',                  v.runs_create),         # POST
    path('tests',                 v.tests_create),        # POST
    path('tests/<int:pk>',        v.tests_update),        # PATCH/PUT, form-encoded
    re_path(r'^baselines/(?P<key>[a-z0-9-]+)\.png$', v.baseline_png),
    re_path(r'^baselines/(?P<key>[a-z0-9-]+)\.json$', v.baseline_json),
]
```

The split into two URL modules makes "is this part of the frozen client contract?" answerable by looking at which file the route lives in. Reviewers should reject any change to `core/urls/legacy.py` or `core/views/legacy.py` that isn't a bug fix.

## View skeletons

### `core/views/legacy.py` — frozen client contract

Function-based DRF views. Field names, parameter shapes, and response keys here are part of the contract — CI clients expect them byte-for-byte. Don't add or rename fields in this module.

```python
# core/views/legacy.py
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Baseline, Project, Run, Suite, Test
from core.serializers import LegacyRunSerializer, LegacyTestSerializer, LegacyBaselineSerializer
from core.services.screenshot_comparison import ScreenshotComparison
from core.services.validation import validate_test_params


@api_view(['POST'])
@parser_classes([FormParser, MultiPartParser])
@permission_classes([AllowAny])
def runs_create(request):
    """POST /runs — find_or_create project + suite, create a fresh run."""
    project_name = request.data.get('project')
    suite_name   = request.data.get('suite')
    project, _ = Project.objects.get_or_create(name=project_name)
    suite,   _ = Suite.objects.get_or_create(project=project, name=suite_name)
    run = Run.objects.create(suite=suite)   # sequential_id assigned in Run.save()
    return Response(LegacyRunSerializer(run).data)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([AllowAny])
def tests_create(request):
    """POST /tests — stage upload, enqueue task, return pending immediately."""
    from core.tasks import process_test
    params = validate_test_params(request.data)
    run = get_object_or_404(Run, pk=params['run_id'])
    test = Test.objects.create(
        run=run, name=params['name'],
        browser=params['browser'], size=params['size'],
        source_url=params.get('source_url'),
        fuzz_level=params['fuzz_level'], highlight_colour=params['highlight_colour'],
        crop_area=params.get('crop_area'),
    )
    staging_key = _stage_upload_to_s3(test.id, request.FILES['screenshot'])
    process_test.delay(test.id, staging_key)
    body = LegacyTestSerializer(test).data
    body['is_new_baseline'] = None
    return Response(body)


@api_view(['GET'])
@permission_classes([AllowAny])
def tests_detail(request, pk):
    """GET /tests/:id/status — poll for async completion."""
    test = get_object_or_404(Test, pk=pk)
    body = LegacyTestSerializer(test).data
    body['is_new_baseline'] = test.is_new_baseline
    return Response(body)


@api_view(['PATCH', 'PUT'])
@parser_classes([FormParser])
@permission_classes([AllowAny])
def tests_update(request, pk):
    """PATCH /tests/:id with test[baseline]=true — 'set as baseline' from the UI."""
    test = get_object_or_404(Test, pk=pk)
    if request.data.get('baseline') == 'true':
        _set_as_baseline(test)
    return Response(LegacyTestSerializer(test).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def baseline_png(request, key):
    baseline = Baseline.objects.filter(key=key).first()
    if not baseline or not baseline.screenshot:
        raise Http404
    return FileResponse(baseline.screenshot.open('rb'), content_type='image/png')


@api_view(['GET'])
@permission_classes([AllowAny])
def baseline_json(request, key):
    baseline = Baseline.objects.filter(key=key).first()
    if not baseline:
        raise Http404
    return Response(LegacyBaselineSerializer(baseline).data)


def _set_as_baseline(test):
    """Promote a previously-failing test to the new baseline. Shared with the SPA endpoint."""
    test.passed = True
    test.save()
    upsert_baseline_from_test(test)   # explicit upsert; no post-save signal
```

### `core/views/api.py` — SPA-internal endpoints

These can evolve. The SPA ships from the same repo, so contract drift is caught at PR time.

```python
# core/views/api.py
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Baseline, Project, Run, Suite, Test
from core.serializers import (
    ProjectSerializer, SuiteDetailSerializer, RunDetailSerializer, BaselineSerializer,
)
from core.views.legacy import _set_as_baseline


@api_view(['GET'])
@permission_classes([AllowAny])
def projects_list(request):
    qs = Project.objects.prefetch_related('suites__runs').order_by('name')
    return Response(ProjectSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def suite_detail(request, project, suite):
    obj = get_object_or_404(
        Suite.objects.select_related('project'),
        project__slug=project, slug=suite,
    )
    return Response(SuiteDetailSerializer(obj).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def run_detail(request, project, suite, seq):
    obj = get_object_or_404(
        Run.objects.select_related('suite__project').prefetch_related('tests'),
        suite__project__slug=project, suite__slug=suite, sequential_id=seq,
    )
    return Response(RunDetailSerializer(obj).data)


@api_view(['POST'])
@permission_classes([AllowAny])
def set_baseline(request, pk):
    """POST /api/tests/<id>/set-baseline/ — JSON, empty body. SPA-preferred shape."""
    test = get_object_or_404(Test, pk=pk)
    _set_as_baseline(test)
    return Response(status=204)


@api_view(['GET'])
@permission_classes([AllowAny])
def baseline_detail(request, key):
    obj = get_object_or_404(Baseline, key=key)
    return Response(BaselineSerializer(obj).data)
```

`_set_as_baseline` is the shared seam between the legacy `PATCH /tests/:id` and the SPA `POST /api/tests/<id>/set-baseline/`. Both endpoints stay thin; the actual baseline-promotion behaviour is in one place and is exercised by the same set of tests.

## Serializers — `core/serializers.py`

Two parallel hierarchies: `Legacy*Serializer` for the frozen client contract and the rest for the SPA. They share nothing except the underlying models — keeping them apart means a change to the SPA shape can never accidentally edit the wire format clients read.

```python
# core/serializers.py
from rest_framework import serializers

from core.models import Baseline, Project, Run, Suite, Test


# ---- Legacy serializers — frozen contract for CI clients -----------

class LegacyRunSerializer(serializers.ModelSerializer):
    """Frozen contract for CI clients. Do not add or rename fields here."""
    url = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ['id', 'suite_id', 'sequential_id', 'created_at', 'updated_at', 'url']

    def get_url(self, obj):
        suite = obj.suite
        return f"/projects/{suite.project.slug}/suites/{suite.slug}/runs/{obj.sequential_id}"


class LegacyTestSerializer(serializers.ModelSerializer):
    """Frozen contract for CI clients. Includes the `passed` ↔ `"pass"` wire mapping.

    The model field is `passed` (Python keyword constraint — see data-model.md), but
    clients expect `"pass"` in the response body. `source='passed'` on a serializer field
    handles both directions: it reads `instance.passed` for output, and `validated_data`
    routes `"pass"` back to `passed` on input.
    """
    pass_field = serializers.BooleanField(source='passed')   # see to_representation override below

    # Dragonfly-style UID columns no longer exist; legacy CI clients read these but
    # never used them as anything other than opaque strings. We emit the S3 URL
    # in their place — same field name, client-compatible interpretation.
    screenshot_uid          = serializers.SerializerMethodField()
    screenshot_baseline_uid = serializers.SerializerMethodField()
    screenshot_diff_uid     = serializers.SerializerMethodField()

    url = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            'id', 'name', 'browser', 'size', 'run_id',
            'diff', 'screenshot_uid', 'screenshot_baseline_uid', 'screenshot_diff_uid',
            'key', 'pass_field', 'source_url', 'fuzz_level', 'highlight_colour', 'crop_area',
            'created_at', 'updated_at', 'url',
        ]

    def to_representation(self, instance):
        # Rename pass_field → "pass" on the way out so clients see the legacy key.
        data = super().to_representation(instance)
        data['pass'] = data.pop('pass_field')
        return data

    def get_screenshot_uid(self, obj):
        return obj.screenshot.url if obj.screenshot else None

    def get_screenshot_baseline_uid(self, obj):
        return obj.screenshot_baseline.url if obj.screenshot_baseline else None

    def get_screenshot_diff_uid(self, obj):
        return obj.screenshot_diff.url if obj.screenshot_diff else None

    def get_url(self, obj):
        suite = obj.run.suite
        return (f"/projects/{suite.project.slug}/suites/{suite.slug}"
                f"/runs/{obj.run.sequential_id}#test_{obj.id}")


class LegacyBaselineSerializer(serializers.ModelSerializer):
    """For GET /baselines/<key>.json — some CI clients read this endpoint."""
    screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = Baseline
        fields = [
            'id', 'name', 'browser', 'size', 'suite_id', 'key', 'test_id',
            'screenshot_url', 'created_at', 'updated_at',
        ]

    def get_screenshot_url(self, obj):
        return obj.screenshot.url if obj.screenshot else None


# ---- SPA serializers — internal, free to evolve ----------------------------

class _ThumbField(serializers.SerializerMethodField):
    """Returns the field's `.url` or None. Drops the dance from each call site."""
    def __init__(self, field_name, **kwargs):
        super().__init__(**kwargs)
        self._target = field_name

    def to_representation(self, value):
        f = getattr(value, self._target)
        return f.url if f else None


class TestRowSerializer(serializers.ModelSerializer):
    """One row in the run-detail table: status, three thumbnails, three full-size URLs."""
    passed = serializers.BooleanField()
    screenshot_url        = _ThumbField('screenshot')
    baseline_url          = _ThumbField('screenshot_baseline')
    diff_url              = _ThumbField('screenshot_diff')
    screenshot_thumb_url  = _ThumbField('screenshot_thumb')
    baseline_thumb_url    = _ThumbField('screenshot_baseline_thumb')
    diff_thumb_url        = _ThumbField('screenshot_diff_thumb')

    class Meta:
        model = Test
        fields = [
            'id', 'name', 'browser', 'size', 'source_url',
            'diff', 'passed', 'key',
            'fuzz_level', 'highlight_colour', 'crop_area',
            'screenshot_url', 'baseline_url', 'diff_url',
            'screenshot_thumb_url', 'baseline_thumb_url', 'diff_thumb_url',
            'created_at',
        ]


class RunSummarySerializer(serializers.ModelSerializer):
    """One row in the suite page's `Latest runs` table — counts only, no test list."""
    passing = serializers.IntegerField(read_only=True)
    failing = serializers.IntegerField(read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'sequential_id', 'created_at', 'passing', 'failing']


class RunDetailSerializer(serializers.ModelSerializer):
    """Run page payload: everything needed to render the test table."""
    tests = TestRowSerializer(many=True, read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'sequential_id', 'created_at', 'tests']


class BaselineSerializer(serializers.ModelSerializer):
    screenshot_url    = _ThumbField('screenshot')
    thumbnail_url     = _ThumbField('thumbnail')

    class Meta:
        model = Baseline
        fields = ['id', 'name', 'browser', 'size', 'key',
                  'screenshot_url', 'thumbnail_url', 'created_at']


class SuiteDetailSerializer(serializers.ModelSerializer):
    """Suite page payload: latest 5 runs (summaries) + all baselines."""
    latest_runs = serializers.SerializerMethodField()
    baselines   = BaselineSerializer(many=True, read_only=True)

    class Meta:
        model = Suite
        fields = ['id', 'name', 'slug', 'latest_runs', 'baselines']

    def get_latest_runs(self, obj):
        # Hardcoded 5 to match the run-retention default; the SPA never sees more.
        runs = obj.runs.all()[:5]
        return RunSummarySerializer(runs, many=True).data


class ProjectSerializer(serializers.ModelSerializer):
    """Top-level projects list. One row per (project, suite) — flattened by the view."""
    suites = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'slug', 'suites']

    def get_suites(self, obj):
        return [
            {
                'id': suite.id,
                'name': suite.name,
                'slug': suite.slug,
                'latest_run': RunSummarySerializer(suite.runs.first()).data if suite.runs.exists() else None,
            }
            for suite in obj.suites.all()
        ]
```

### Why two serializer hierarchies, not one with conditionals

The legacy contract is frozen. The SPA contract evolves. If they share a base class, a refactor of the SPA shape — adding a field, renaming a key, changing a default — could leak into the gem's wire format. Two parallel files with no shared base mean the legacy serializer can only break if someone *explicitly* edits it, and a code review catching that is trivial.

The cost is some duplication: both serializers know how to produce a Test's URL, both expose `key`. That's a deliberate trade — duplicated lines in serializers are cheaper than a wire-format regression that breaks every CI pipeline using the legacy API.

### The `passed` ↔ `"pass"` mapping

Three pieces:

1. **Model field is `passed`** (Python keyword constraint — see [data-model.md](data-model.md)).
2. **DRF field is `pass_field` with `source='passed'`** so it reads from the model.
3. **`to_representation` renames `pass_field` → `"pass"`** on the way out, so clients see the legacy key.

Inbound traffic doesn't need the reverse mapping: legacy CI clients don't post `"pass"` (they only post crop/fuzz/colour parameters), and "set as baseline" reads `request.data.get('baseline')`, not `"pass"`. The mapping is one-way: model → wire.

### Test surface

This module is the second-highest-leverage place to test, after `screenshot_comparison.py`. Minimum coverage:

- `LegacyTestSerializer` output **always** has the key `"pass"`, never `"passed"` or `"pass_field"`. This is the single-line check that catches every wire-format regression.
- `LegacyTestSerializer` field set is exactly the legacy set (assert against a frozen list — adding a field to the model must not silently appear in the legacy response).
- `LegacyRunSerializer.url` matches the slug-based path even after a project rename ([decisions.md](decisions.md) #4).
- `TestRowSerializer` URLs are `None` when the underlying `FileField` is unset (i.e. mid-comparison).
- `SuiteDetailSerializer.latest_runs` returns at most 5 entries.

This doc is narrative. The next step is an **OpenAPI 3 spec** at `docs/openapi.yaml`, generated from DRF via `drf-spectacular`. It would:

- Pin field names and types on `POST /runs`, `POST /tests`, `PATCH /tests/:id`, `GET /baselines/:key` so any drift breaks CI, not production.
- Generate a contract test suite (e.g. `schemathesis run docs/openapi.yaml`) that hits a running instance with CI client payload shapes.
- Give the SPA typed clients via `openapi-generator`.

Not in scope for the rebuild docs themselves; flagged here so it doesn't get lost when implementation starts.

## CSRF, CORS, and content-types

- Today: CSRF is per-form, the API endpoints opt out, JSON wrap_parameters is on. No CORS config (browser-side AJAX is same-origin).
- Rebuild: with a separate Angular frontend on a different origin/port, CORS becomes mandatory. Configure `django-cors-headers` to allow the SPA origin.
