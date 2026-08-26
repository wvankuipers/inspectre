"""Frozen API contract — field names, parameter shapes, and response keys are
part of the Client API expectations. Do not add or rename fields.
"""

from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Baseline, Project, Run, Suite, Test
from core.serializers import (
    LegacyBaselineSerializer,
    LegacyRunSerializer,
    LegacyTestSerializer,
)
from core.services.validation import validate_test_params
from core.tasks import process_test


@api_view(["POST"])
@parser_classes([FormParser, MultiPartParser])
@permission_classes([AllowAny])
def runs_create(request):
    """POST /runs — find_or_create project + suite, create a fresh run."""
    project_name = (request.data.get("project") or "").strip()
    suite_name = (request.data.get("suite") or "").strip()
    errors = {}
    if not project_name:
        errors["project"] = "is required"
    if not suite_name:
        errors["suite"] = "is required"
    if errors:
        raise ValidationError(errors)
    project, _ = Project.objects.get_or_create(name=project_name)
    suite, _ = Suite.objects.get_or_create(project=project, name=suite_name)
    run = Run.objects.create(suite=suite)  # sequential_id assigned in Run.save()
    return Response(LegacyRunSerializer(run).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([AllowAny])
def tests_create(request):
    """POST /tests — enqueues async diff. Returns immediately with status=pending."""
    params = validate_test_params(request.data)  # 400 if shell-injection regexes fail

    screenshot = request.FILES.get("screenshot")
    if not screenshot:
        raise ValidationError({"screenshot": "is required"})

    run = get_object_or_404(Run.objects.select_related("suite__project"), pk=params["run_id"])

    test = Test.objects.create(
        run=run,
        name=params["name"],
        browser=params["browser"],
        size=params["size"],
        source_url=params["source_url"],
        fuzz_level=params["fuzz_level"],
        highlight_colour=params["highlight_colour"],
        crop_area=params["crop_area"],
    )

    staging_key = _stage_upload_to_s3(test.id, screenshot)
    process_test.delay(test.id, staging_key)

    body = LegacyTestSerializer(test).data
    body["is_new_baseline"] = None
    return Response(body)


@api_view(["GET"])
@permission_classes([AllowAny])
def tests_detail(request, pk):
    """GET /tests/:id/status — poll for async processing result."""
    test = get_object_or_404(Test, pk=pk)
    body = LegacyTestSerializer(test).data
    body["is_new_baseline"] = test.is_new_baseline
    return Response(body)


@api_view(["PATCH", "PUT"])
@parser_classes([FormParser, MultiPartParser])
@permission_classes([AllowAny])
def tests_update(request, pk):
    """PATCH /tests/:id with test[baseline]=true — 'set as baseline' from the UI."""
    test = get_object_or_404(Test, pk=pk)
    if request.data.get("test[baseline]") == "true":
        _set_as_baseline(test)
    return Response(LegacyTestSerializer(test).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def baseline_png(request, key):
    baseline = Baseline.objects.filter(key=key).first()
    if not baseline or not baseline.screenshot:
        raise Http404
    return FileResponse(
        baseline.screenshot.open("rb"),
        content_type="image/png",
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def baseline_json(request, key):
    baseline = Baseline.objects.filter(key=key).first()
    if not baseline:
        raise Http404
    return Response(LegacyBaselineSerializer(baseline).data)


def _set_as_baseline(test):
    """Promote a previously-failing test to the new baseline. Shared with the SPA endpoint.

    Mirrors the legacy Test#after_save :update_baseline path: when passed flips
    to True, the most recent passing screenshot replaces the baseline for this key.
    """
    from core.services.baseline_upsert import attach_baseline_thumbnail_for_test, upsert_baseline_row

    with transaction.atomic():
        test.passed = True
        test.save()
        baseline = upsert_baseline_row(test)
    attach_baseline_thumbnail_for_test(baseline, test)


def _stage_upload_to_s3(test_id: int, uploaded_file) -> str:
    """Upload the raw screenshot to a staging key in S3, returning the key."""
    from django.conf import settings as django_settings

    from core.services.s3 import get_s3_client

    staging_key = f"screenshots/staging/{test_id}/upload.png"
    get_s3_client().upload_fileobj(uploaded_file, django_settings.AWS_STORAGE_BUCKET_NAME, staging_key)
    return staging_key
