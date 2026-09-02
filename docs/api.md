# HTTP API

There is **no authentication** on any endpoint. CSRF protection is not required on the legacy endpoints since DRF's `AllowAny` permission class is used without session authentication.

## Route table

This is the current Django/DRF backend. All routes are unauthenticated (`AllowAny`); there is no session/CSRF layer on any of them.

> **Historical note:** an earlier Rails-era (and, in places, purely aspirational) version of this doc described HTML routes — `GET /`, `GET /projects`, `GET /projects/:project_slug/suites/:slug`, `GET /projects/:project_slug/suites/:suite_slug/runs/:sequential_id` (HTML), `GET /runs/new`, `GET /tests/new` — and a Dragonfly-backed `/media/:job/:name` image route. None of these exist in the current backend. The SPA is served as a static Angular bundle by nginx and talks to the API purely over JSON under `/api/*`; there are no server-rendered HTML pages. Screenshots are served from S3/MinIO via presigned URLs, not a Dragonfly middleware route.

### Legacy (Client API) routes — frozen, un-prefixed

Defined in `backend/core/urls/legacy.py`. These exist to keep existing CI clients working unchanged; see [decisions.md](decisions.md) #7.

| Method    | Path                  | View                | Notes |
| --------- | --------------------- | ------------------- | ----- |
| POST      | `/runs`                | `runs_create`       | JSON body in response; form-encoded/multipart request |
| POST      | `/tests`               | `tests_create`      | multipart/form-data; enqueues async diff |
| GET       | `/tests/:id/status`    | `tests_detail`      | Poll for async completion |
| PATCH/PUT | `/tests/:id`           | `tests_update`      | "Set as baseline"; form-encoded |
| GET       | `/baselines/:key.png`  | `baseline_png`      | Streams the PNG binary |
| GET       | `/baselines/:key.json` | `baseline_json`     | Baseline record as JSON |

### SPA endpoints — `/api/*`, free to evolve

Defined in `backend/core/urls/spa.py`. Consumed only by the Angular frontend; not part of the frozen Client API contract.

| Method | Path                                                                       | View            | Notes |
| ------ | --------------------------------------------------------------------------- | --------------- | ----- |
| GET    | `/api/projects/`                                                            | `projects_list` | Flattened project+suite rows |
| GET    | `/api/projects/<slug>/suites/<slug>/`                                       | `suite_detail`  | Latest 5 runs + baselines |
| GET    | `/api/projects/<slug>/suites/<slug>/runs/<seq>/`                            | `run_detail`    | Run + test table |
| GET    | `/api/projects/<slug>/suites/<slug>/tests/<key>/`                          | `test_history`  | Cross-run pass/fail history for one test key |
| POST   | `/api/tests/bulk/`                                                          | `tests_bulk`    | Fetch fresh `TestRow` data for a set of ids (polling) |
| POST   | `/api/tests/<id>/set-baseline/`                                             | `set_baseline`  | JSON, empty body |
| GET    | `/api/baselines/<key>/`                                                     | `baseline_detail` | Baseline JSON metadata |

### Infrastructure and admin

| Method | Path        | View            | Notes |
| ------ | ----------- | --------------- | ----- |
| any    | `/admin/*`  | Django admin    | Full CRUD UI; session-authenticated |
| GET    | `/healthz/` | `health.healthz` | Dependency-free health check for Kubernetes probes; not part of either the SPA or legacy Client API surface |

## Endpoints in detail

### `POST /runs`

Creates (or reuses) a project + suite, then creates a fresh run.

Request (form-encoded or multipart; the view only declares `FormParser`/`MultiPartParser`, no JSON parser):

```http
POST /runs
Content-Type: application/x-www-form-urlencoded

project=Acme%20Site&suite=Desktop
```

Behaviour: `Project.objects.get_or_create(name=...)` then `Suite.objects.get_or_create(project=..., name=...)` then `Run.objects.create(suite=...)`. The view strips leading/trailing whitespace from `project` and `suite` before the lookup (`project_name = (request.data.get("project") or "").strip()`), so submitting `"Acme Site "` (trailing space) resolves to the same project as `"Acme Site"` — it does **not** create a different project. There is no slug-based lookup at ingest.

If `project` or `suite` is missing (or blank after stripping), the view returns `400` with a field-keyed error body, e.g. `{"project": "is required"}` and/or `{"suite": "is required"}`.

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
- Missing `run_id` (or missing `name`/`browser`/`size`) → 400, via `validate_test_params` (`backend/core/services/validation.py`).
- `run_id` present but no matching `Run` → 404.
- Missing `screenshot` → 400.
- Malformed `fuzz_level`, `highlight_colour`, or `crop_area` → 400. Each is validated against a strict, fully-anchored regex before it can reach the ImageMagick command line — this is shell-injection protection, since the legacy app used to interpolate these values directly into a shell command (`backend/core/services/validation.py`):
  - `fuzz_level` must match `\d+(\.\d+)?%` and be `<= 100%` (default `"30%"`).
  - `highlight_colour` must match `[0-9a-fA-F]{6}` (default `"ff0000"`, no leading `#`).
  - `crop_area` must match `\d+x\d+\+\d+\+\d+` when non-empty.
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
  "pass": false,
  "diff": 0,
  "screenshot_uid": "http://localhost:9000/inspectre-screenshots/screenshots/1234/original.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=...&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=...",
  "screenshot_baseline_uid": null,
  "screenshot_diff_uid": null,
  "is_new_baseline": true,
  ...
}
```

This example shows a first-ever submission for its key: `pass` is `false` and there's nothing to compare against, so `screenshot_baseline_uid`/`screenshot_diff_uid` stay `null` until a human approves it (see below). A normal comparison against an existing baseline would instead populate those URLs and set `pass` based on the diff percentage.

The bucket is private, so these are presigned URLs with a 24-hour expiry. Clients should treat each URL as a transient signed link, not a stable identifier to cache or compare — it will stop working once it expires.

`is_new_baseline: true` means this submission had nothing to compare against — either no Baseline row exists yet for the key, or its file is missing from storage. There is no Baseline to diff against, so `screenshot_baseline_uid` and `screenshot_diff_uid` are `null`, and `pass` will be `false` until a human approves it via `PATCH /tests/:id` with `test[baseline]=true` (see "Set as baseline" below) — it does not pass or become the Baseline automatically. A subsequent submission for the same key, made after approval, will have `is_new_baseline: false` and populated `screenshot_baseline_uid` / `screenshot_diff_uid` URLs. Surfaced as a chip in the SPA ([ui.md](ui.md)).

### `PATCH /tests/:id` ("Set as baseline")

Used by the UI when a human accepts a previously-failing test as the new baseline.

Request:

```http
PATCH /tests/1234
test[baseline]=true
```

Behaviour:
- If `request.data.get("test[baseline]") == "true"`, promotes the test: sets `passed = True`, saves, and upserts the Baseline row with this test's screenshot.
- Any other value is a no-op; the test record is returned unchanged.

Note: the view only acts on `test[baseline]=true`. The SPA uses `POST /api/tests/<id>/set-baseline/` instead (same underlying logic).

### `GET /baselines/:key.png` and `GET /baselines/:key.json`

Public read of a baseline by its key. The extension selects the response format:

- `/baselines/:key.png` → streams the screenshot binary inline (`image/png`).
- `/baselines/:key.json` → returns the Baseline record as JSON.

404 if no Baseline matches the key.

> **Historical note:** an earlier version of this doc described `GET /projects/:project_slug/suites/:suite_slug/runs/:sequential_id` as an HTML-or-JSON Rails route, plus `GET /runs/new` / `GET /tests/new` hand-testing forms and a Dragonfly-backed `/media/:job/:name` image route. None of these exist in the current Django backend — there are no server-rendered HTML pages, and screenshots are served from S3/MinIO. The current equivalent of the run page is the SPA endpoint `GET /api/projects/<slug>/suites/<slug>/runs/<seq>/` (below), which returns JSON only.

### `/admin/*`

Full CRUD over Project / Suite / Run / Test / Baseline. See [admin.md](admin.md).

### SPA endpoints (`/api/*`)

These back the Angular frontend and are free to evolve — see the [route table](#spa-endpoints--api-free-to-evolve) above for the full list. Two are otherwise undocumented:

- **`GET /api/projects/<slug>/suites/<slug>/tests/<key>/`** (`test_history`) — returns the cross-run pass/fail history for a single test key within a suite, newest run first. 404 if no `Test` rows match. Response shape (via `serialize_test_history`):

  ```json
  {
    "key": "acme-site-desktop-homepage-chrome-1024",
    "name": "Homepage",
    "browser": "Chrome",
    "size": "1024",
    "project_name": "Acme Site",
    "suite_slug": "desktop",
    "runs": [
      {
        "id": 1234,
        "run_id": 42,
        "run_sequential_id": 12,
        "run_created_at": "...",
        "original_passed": false,
        "is_new_baseline": true,
        "status": "done",
        "screenshot_thumb_url": "https://..."
      }
    ]
  }
  ```

  Each entry in `runs` is a `TestHistoryEntrySerializer` row. It deliberately serializes `original_passed` — the tamper-proof snapshot of the test's first-ever pass/fail result — rather than the mutable `passed` field, since baseline promotion can flip `passed` after the fact and the history view is meant to show what actually happened at each run.

- **`POST /api/tests/bulk/`** (`tests_bulk`) — fetches fresh `TestRow` data for a set of ids in one request, used by the SPA's polling loop while tests are still `pending`/`processing`. Request body: `{"ids": [1234, 1235, ...]}`. Behaviour (`backend/core/views/api.py`):
  - Non-list `ids`, or a missing key, is treated as `[]`.
  - Non-integer entries (including booleans, since `bool` is a subclass of `int` in Python) are silently dropped rather than causing a 400.
  - Duplicate ids are collapsed.
  - The (deduplicated) id list is truncated to `MAX_BULK_TEST_IDS = 1000` — a large or malicious id list is silently capped, not rejected.
  - Response is a list of `TestRowSerializer` rows (via `serialize_tests_bulk`) for whichever ids matched an existing `Test`; unknown ids are simply absent from the response, not reported as errors.

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
    path('projects/<slug:project>/suites/<slug:suite>/tests/<str:key>/', v.test_history),  # GET, cross-run history
    path('tests/bulk/',                                        v.tests_bulk),  # POST, JSON
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
    path('tests/<int:pk>/status', v.tests_detail),        # GET — poll for async status
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
    if request.data.get('test[baseline]') == 'true':
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
            'created_at', 'updated_at', 'url', 'status',
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
    """One row in the run-detail table: status, three thumbnails, three full-size URLs.

    `is_baseline_source` is True when this test is the producer of the current
    Baseline for its key. `has_baseline` means "does any Baseline exist for this
    key at all" — it drives the SPA's "New baseline" chip and stays true even
    after supersession by a newer baseline. Both are resolved via context
    populated by the caller (`RunDetailSerializer`, `serialize_tests_bulk`) to
    avoid N+1 queries.
    """
    passed = serializers.BooleanField()
    is_baseline_source    = serializers.SerializerMethodField()
    has_baseline           = serializers.SerializerMethodField()
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
            'diff', 'passed', 'key', 'is_baseline_source', 'has_baseline',
            'fuzz_level', 'highlight_colour', 'crop_area',
            'screenshot_url', 'baseline_url', 'diff_url',
            'screenshot_thumb_url', 'baseline_thumb_url', 'diff_thumb_url',
            'created_at', 'status',
        ]


class RunSummarySerializer(serializers.ModelSerializer):
    """One row in the suite page's `Latest runs` table — counts only, no test list."""
    passing     = serializers.IntegerField(read_only=True)
    failing     = serializers.IntegerField(read_only=True)
    unbaselined = serializers.IntegerField(read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'sequential_id', 'created_at', 'passing', 'failing', 'unbaselined']


class RunDetailSerializer(serializers.ModelSerializer):
    """Run page payload: everything needed to render the test table."""
    project_name = serializers.SerializerMethodField()
    tests = TestRowSerializer(many=True, read_only=True)

    class Meta:
        model = Run
        fields = ['id', 'sequential_id', 'created_at', 'project_name', 'tests']


class BaselineSerializer(serializers.ModelSerializer):
    screenshot_url    = _ThumbField('screenshot')
    thumbnail_url     = _ThumbField('thumbnail')

    class Meta:
        model = Baseline
        fields = ['id', 'name', 'browser', 'size', 'key',
                  'screenshot_url', 'thumbnail_url', 'created_at']


class SuiteDetailSerializer(serializers.ModelSerializer):
    """Suite page payload: latest 5 runs (summaries) + all baselines."""
    project_name = serializers.SerializerMethodField()
    latest_runs = serializers.SerializerMethodField()
    baselines   = BaselineSerializer(many=True, read_only=True)

    class Meta:
        model = Suite
        fields = ['id', 'name', 'slug', 'project_name', 'latest_runs', 'baselines']

    def get_project_name(self, obj):
        return obj.project.name

    def get_latest_runs(self, obj):
        # Hardcoded 5 to match the run-retention default; the SPA never sees more.
        runs = obj.runs.all()[:5]
        return RunSummarySerializer(runs, many=True).data


class TestHistoryEntrySerializer(serializers.ModelSerializer):
    """One row in a test's cross-run history: the immutable `original_passed`
    result, not the mutable `passed` field (which baseline promotion can flip).
    """
    run_sequential_id   = serializers.SerializerMethodField()
    run_created_at       = serializers.SerializerMethodField()
    screenshot_thumb_url = _ThumbField('screenshot_thumb')

    class Meta:
        model = Test
        fields = [
            'id', 'run_id', 'run_sequential_id', 'run_created_at',
            'original_passed', 'is_new_baseline', 'status', 'screenshot_thumb_url',
        ]


def serialize_test_history(tests, key):
    """Serialize one test key's ordered history of Test rows (newest run first).

    Backs `GET /api/projects/<slug>/suites/<slug>/tests/<key>/`.
    """
    first = tests[0]
    return {
        'key': key,
        'name': first.name,
        'browser': first.browser,
        'size': first.size,
        'project_name': first.run.suite.project.name,
        'suite_slug': first.run.suite.slug,
        'runs': TestHistoryEntrySerializer(tests, many=True).data,
    }


def serialize_tests_bulk(tests):
    """Serialize an arbitrary set of Test rows (may span multiple suites/runs).

    Backs `POST /api/tests/bulk/`. Mirrors `RunDetailSerializer`'s baseline-source
    resolution, but grouped per suite since the input isn't guaranteed to be one suite.
    """
    tests = list(tests)
    suite_ids = {t.run.suite_id for t in tests}
    baseline_source_ids = {
        b.test_id for b in Baseline.objects.filter(suite_id__in=suite_ids, test_id__isnull=False)
    }
    baselined_keys = {b.key for b in Baseline.objects.filter(suite_id__in=suite_ids)}
    return TestRowSerializer(
        tests, many=True,
        context={'baseline_source_ids': baseline_source_ids, 'baselined_keys': baselined_keys},
    ).data


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

Inbound traffic doesn't need the reverse mapping: legacy CI clients don't post `"pass"` (they only post crop/fuzz/colour parameters), and "set as baseline" reads `request.data.get('test[baseline]')`, not `"pass"`. The mapping is one-way: model → wire.

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

- Today: there is no session authentication on any endpoint, so DRF never enforces CSRF here. The legacy views only declare `FormParser`/`MultiPartParser` (no JSON parser) — clients must post form-encoded or multipart bodies, not `application/json`. No CORS config (browser-side AJAX is same-origin, since the SPA is served by the same nginx that proxies to the API).
- Rebuild: with a separate Angular frontend on a different origin/port, CORS becomes mandatory. Configure `django-cors-headers` to allow the SPA origin.
