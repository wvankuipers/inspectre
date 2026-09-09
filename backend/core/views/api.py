"""SPA-internal endpoints (`/api/*`).

These can evolve. The SPA ships from the same repo, so contract drift is
caught at PR time. The legacy endpoints (POST /runs, POST /tests, PATCH
/tests/<id>, GET /baselines/<key>.png|.json) live in views/legacy.py and are
frozen for Client API compatibility.
"""

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Baseline, Project, Run, Suite, Test
from core.serializers import (
    BaselineSerializer,
    ProjectDetailSerializer,
    ProjectSerializer,
    RunDetailSerializer,
    SuiteDetailSerializer,
    build_project_aggregates,
    compute_run_verdict,
    serialize_test_history,
    serialize_tests_bulk,
)
from core.views.legacy import _set_as_baseline

# Caps the ids a single POST /api/tests/bulk/ request can request, since a
# run's pending set is client-controlled: an unbounded id list means an
# unbounded IN() query and serializer pass.
MAX_BULK_TEST_IDS = 1000


@api_view(["GET"])
@permission_classes([AllowAny])
def projects_list(request):
    qs = Project.objects.prefetch_related("suites__runs").order_by("name")
    project_aggregates = build_project_aggregates(qs)
    return Response(ProjectSerializer(qs, many=True, context={"project_aggregates": project_aggregates}).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def project_detail(request, project):
    obj = get_object_or_404(Project.objects.prefetch_related("suites__runs"), slug=project)
    return Response(ProjectDetailSerializer(obj).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def suite_detail(request, project, suite):
    obj = get_object_or_404(
        Suite.objects.select_related("project"),
        project__slug=project,
        slug=suite,
    )
    return Response(SuiteDetailSerializer(obj).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def run_detail(request, project, suite, seq):
    obj = get_object_or_404(
        Run.objects.select_related("suite__project").prefetch_related("tests"),
        suite__project__slug=project,
        suite__slug=suite,
        sequential_id=seq,
    )
    return Response(RunDetailSerializer(obj).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def test_history(request, project, suite, key):
    tests = list(
        Test.objects.select_related("run__suite__project")
        .filter(run__suite__project__slug=project, run__suite__slug=suite, key=key)
        .order_by("-run__sequential_id")
    )
    if not tests:
        raise Http404
    return Response(serialize_test_history(tests, key))


@api_view(["POST"])
@permission_classes([AllowAny])
def set_baseline(request, pk):
    """POST /api/tests/<id>/set-baseline/ — JSON, empty body. SPA-preferred shape.

    Body is intentionally ignored: a malicious client cannot un-promote a baseline
    by sending {"pass": false}. Always promotes.
    """
    test = get_object_or_404(Test, pk=pk)
    _set_as_baseline(test)
    return Response(status=204)


@api_view(["POST"])
@permission_classes([AllowAny])
def tests_bulk(request):
    """POST /api/tests/bulk/ — fetch fresh TestRow data for a set of ids.

    IDs travel in the body, not the URL: a run's pending set can be large
    (hundreds of tests), which doesn't fit a query string or path segment.
    Unknown ids (including non-integers) are silently omitted rather than causing
    an error, since the caller already knows which ids it's polling for. The
    unique id count is capped at MAX_BULK_TEST_IDS to bound the query and
    serialization work for a single request.
    """
    raw = request.data.get("ids") if isinstance(request.data, dict) else None
    if not isinstance(raw, (list, tuple)):
        raw = []
    ids = list(dict.fromkeys(i for i in raw if isinstance(i, int) and not isinstance(i, bool)))
    ids = ids[:MAX_BULK_TEST_IDS]
    tests = Test.objects.select_related("run__suite__project").filter(id__in=ids)
    return Response(serialize_tests_bulk(tests))


@api_view(["GET"])
@permission_classes([AllowAny])
def baseline_detail(request, key):
    obj = get_object_or_404(Baseline, key=key)
    return Response(BaselineSerializer(obj).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def run_validate(request, project, suite, seq):
    obj = get_object_or_404(
        Run.objects.select_related("suite__project"),
        suite__project__slug=project,
        suite__slug=suite,
        sequential_id=seq,
    )
    return Response(compute_run_verdict(obj.tests.values_list("status", "passed")))


@api_view(["GET"])
@permission_classes([AllowAny])
def project_validate(request, project):
    obj = get_object_or_404(Project.objects.prefetch_related("suites__runs"), slug=project)
    latest_run_by_suite = {}
    for suite in obj.suites.all():
        latest_run_by_suite[suite] = suite.runs.first()

    # Batch every suite's latest-run tests into ONE query, regardless of suite
    # count — mirrors build_run_counts's batching discipline. Without this,
    # compute_run_verdict's per-run values_list() call would issue one query per
    # suite (a real N+1).
    run_ids = [run.id for run in latest_run_by_suite.values() if run is not None]
    rows_by_run = {run_id: [] for run_id in run_ids}
    for run_id, status, passed in Test.objects.filter(run_id__in=run_ids).values_list("run_id", "status", "passed"):
        rows_by_run[run_id].append((status, passed))

    suites = []
    for suite, latest_run in latest_run_by_suite.items():
        if latest_run is None:
            suites.append(
                {
                    "suite": suite.slug,
                    "run_sequential_id": None,
                    "status": "failed",
                    "passing": 0,
                    "failing": 0,
                    "pending": 0,
                    "total": 0,
                }
            )
            continue
        verdict = compute_run_verdict(rows_by_run[latest_run.id])
        suites.append({"suite": suite.slug, "run_sequential_id": latest_run.sequential_id, **verdict})

    if not suites:
        # A project with zero suites has never had a chance to pass — an empty/
        # unreached state must never read as a clean gate (same "never vacuously
        # pass" pattern as a suite with zero runs, or a run with zero tests).
        overall = "pending"
    else:
        statuses = {s["status"] for s in suites}
        if "failed" in statuses:
            overall = "failed"
        elif "pending" in statuses:
            overall = "pending"
        else:
            overall = "passed"
    return Response({"status": overall, "suites": suites})
