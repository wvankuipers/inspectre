"""SPA-internal endpoints (`/api/*`).

These can evolve. The SPA ships from the same repo, so contract drift is
caught at PR time. The legacy endpoints (POST /runs, POST /tests, PATCH
/tests/<id>, GET /baselines/<key>.png|.json) live in views/legacy.py and are
frozen for Client API compatibility.
"""

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Baseline, Project, Run, Suite, Test
from core.serializers import (
    BaselineSerializer,
    ProjectSerializer,
    RunDetailSerializer,
    SuiteDetailSerializer,
)
from core.views.legacy import _set_as_baseline


@api_view(["GET"])
@permission_classes([AllowAny])
def projects_list(request):
    qs = Project.objects.prefetch_related("suites__runs").order_by("name")
    return Response(ProjectSerializer(qs, many=True).data)


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


@api_view(["GET"])
@permission_classes([AllowAny])
def baseline_detail(request, key):
    obj = get_object_or_404(Baseline, key=key)
    return Response(BaselineSerializer(obj).data)
