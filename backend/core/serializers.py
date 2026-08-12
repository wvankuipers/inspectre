from rest_framework import serializers

from core.models import Baseline, Project, Run, Suite, Test
from core.services.s3 import generate_presigned_url

# ---- Legacy serializers — frozen contract for legacy clients -----------


class LegacyRunSerializer(serializers.ModelSerializer):
    """Frozen contract for CI clients. Do not add or rename fields here."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ["id", "suite_id", "sequential_id", "created_at", "updated_at", "url"]

    def get_url(self, obj):
        suite = obj.suite
        return f"/projects/{suite.project.slug}/suites/{suite.slug}/runs/{obj.sequential_id}"


class LegacyTestSerializer(serializers.ModelSerializer):
    """Frozen contract for CI clients. Includes the `passed` ↔ `"pass"` wire mapping.

    The model field is `passed` (Python keyword constraint — see data-model.md), but
    clients expect `"pass"` in the response body.
    """

    pass_field = serializers.BooleanField(source="passed")

    screenshot_uid = serializers.SerializerMethodField()
    screenshot_baseline_uid = serializers.SerializerMethodField()
    screenshot_diff_uid = serializers.SerializerMethodField()

    url = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            "id",
            "name",
            "browser",
            "size",
            "run_id",
            "diff",
            "screenshot_uid",
            "screenshot_baseline_uid",
            "screenshot_diff_uid",
            "key",
            "pass_field",
            "source_url",
            "fuzz_level",
            "highlight_colour",
            "crop_area",
            "created_at",
            "updated_at",
            "url",
            "status",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["pass"] = data.pop("pass_field")
        return data

    def get_screenshot_uid(self, obj):
        return _file_url(obj.screenshot)

    def get_screenshot_baseline_uid(self, obj):
        return _file_url(obj.screenshot_baseline)

    def get_screenshot_diff_uid(self, obj):
        return _file_url(obj.screenshot_diff)

    def get_url(self, obj):
        suite = obj.run.suite
        return f"/projects/{suite.project.slug}/suites/{suite.slug}/runs/{obj.run.sequential_id}#test_{obj.id}"


class LegacyBaselineSerializer(serializers.ModelSerializer):
    """For GET /baselines/<key>.json — some CI clients read this endpoint."""

    screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = Baseline
        fields = [
            "id",
            "name",
            "browser",
            "size",
            "suite_id",
            "key",
            "test_id",
            "screenshot_url",
            "created_at",
            "updated_at",
        ]

    def get_screenshot_url(self, obj):
        return _file_url(obj.screenshot)


# ---- SPA serializers — internal, free to evolve ----------------------------


def _file_url(field):
    return generate_presigned_url(field.name) if field else None


class TestRowSerializer(serializers.ModelSerializer):
    """One row in the run-detail table: status, three thumbnails, three full-size URLs.

    `is_baseline_source` is True when this test is the producer of the current
    Baseline for its key — surfaces decisions.md #3's "new baseline" badge in
    the SPA. Resolved via context['baseline_source_ids'] populated by
    RunDetailSerializer to avoid N+1 queries.
    """

    passed = serializers.BooleanField()
    is_baseline_source = serializers.SerializerMethodField()
    screenshot_url = serializers.SerializerMethodField()
    baseline_url = serializers.SerializerMethodField()
    diff_url = serializers.SerializerMethodField()
    screenshot_thumb_url = serializers.SerializerMethodField()
    baseline_thumb_url = serializers.SerializerMethodField()
    diff_thumb_url = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            "id",
            "name",
            "browser",
            "size",
            "source_url",
            "diff",
            "passed",
            "key",
            "is_baseline_source",
            "fuzz_level",
            "highlight_colour",
            "crop_area",
            "screenshot_url",
            "baseline_url",
            "diff_url",
            "screenshot_thumb_url",
            "baseline_thumb_url",
            "diff_thumb_url",
            "created_at",
            "status",
        ]

    def get_is_baseline_source(self, obj):
        baseline_source_ids = self.context.get("baseline_source_ids") or set()
        return obj.id in baseline_source_ids

    def get_screenshot_url(self, obj):
        return _file_url(obj.screenshot)

    def get_baseline_url(self, obj):
        return _file_url(obj.screenshot_baseline)

    def get_diff_url(self, obj):
        return _file_url(obj.screenshot_diff)

    def get_screenshot_thumb_url(self, obj):
        return _file_url(obj.screenshot_thumb)

    def get_baseline_thumb_url(self, obj):
        return _file_url(obj.screenshot_baseline_thumb)

    def get_diff_thumb_url(self, obj):
        return _file_url(obj.screenshot_diff_thumb)


def serialize_tests_bulk(tests):
    """Serialize an arbitrary set of Test rows (may span multiple suites/runs).

    Mirrors RunDetailSerializer.get_tests's baseline-source resolution, but
    grouped per suite since the input isn't guaranteed to be one suite.
    """
    tests = list(tests)
    suite_ids = {t.run.suite_id for t in tests}
    baseline_source_ids = set(
        Baseline.objects.filter(suite_id__in=suite_ids, test_id__isnull=False).values_list(
            "test_id", flat=True
        )
    )
    return TestRowSerializer(
        tests,
        many=True,
        context={"baseline_source_ids": baseline_source_ids},
    ).data


class RunSummarySerializer(serializers.ModelSerializer):
    """One row in the suite page's `Latest runs` table — counts only, no test list."""

    passing = serializers.SerializerMethodField()
    failing = serializers.SerializerMethodField()
    unbaselined = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ["id", "sequential_id", "created_at", "passing", "failing", "unbaselined"]

    def get_passing(self, obj):
        return obj.tests.filter(passed=True).count()

    def get_failing(self, obj):
        return obj.tests.filter(passed=False).count()

    def get_unbaselined(self, obj):
        # Use pre-fetched keys from context when available (set by SuiteDetailSerializer
        # to avoid N+1 queries). Falls back to a direct query for standalone use.
        baselined_keys = self.context.get("baselined_keys") or set(
            Baseline.objects.filter(suite_id=obj.suite_id).values_list("key", flat=True)
        )
        return obj.tests.exclude(key__in=baselined_keys).count()


class RunDetailSerializer(serializers.ModelSerializer):
    """Run page payload: everything needed to render the test table."""

    project_name = serializers.SerializerMethodField()
    tests = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ["id", "sequential_id", "created_at", "project_name", "tests"]

    def get_project_name(self, obj):
        return obj.suite.project.name

    def get_tests(self, obj):
        # Resolve "which test ids are the source of a current Baseline" once
        # for the suite, then pass it down to TestRowSerializer via context.
        # Avoids one Baseline query per row.
        baseline_source_ids = set(
            Baseline.objects.filter(suite_id=obj.suite_id, test_id__isnull=False).values_list("test_id", flat=True)
        )
        return TestRowSerializer(
            obj.tests.all(),
            many=True,
            context={"baseline_source_ids": baseline_source_ids},
        ).data


class BaselineSerializer(serializers.ModelSerializer):
    screenshot_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Baseline
        fields = ["id", "name", "browser", "size", "key", "screenshot_url", "thumbnail_url", "created_at"]

    def get_screenshot_url(self, obj):
        return _file_url(obj.screenshot)

    def get_thumbnail_url(self, obj):
        return _file_url(obj.thumbnail)


class SuiteDetailSerializer(serializers.ModelSerializer):
    """Suite page payload: latest 5 runs (summaries) + all baselines."""

    project_name = serializers.SerializerMethodField()
    latest_runs = serializers.SerializerMethodField()
    baselines = BaselineSerializer(many=True, read_only=True)

    class Meta:
        model = Suite
        fields = ["id", "name", "slug", "project_name", "latest_runs", "baselines"]

    def get_project_name(self, obj):
        return obj.project.name

    def get_latest_runs(self, obj):
        runs = obj.runs.all()[:5]
        # Pre-fetch baseline keys once for the suite so RunSummarySerializer.get_unbaselined
        # doesn't issue one Baseline query per run (same pattern as RunDetailSerializer).
        baselined_keys = set(Baseline.objects.filter(suite_id=obj.pk).values_list("key", flat=True))
        return RunSummarySerializer(runs, many=True, context={"baselined_keys": baselined_keys}).data


class ProjectSerializer(serializers.ModelSerializer):
    """Top-level projects list. One row per (project, suite) — flattened by the view."""

    suites = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "slug", "suites"]

    def get_suites(self, obj):
        result = []
        for suite in obj.suites.all():
            runs = suite.runs.all()  # hits prefetch cache, no extra query
            latest = runs[0] if runs else None
            result.append(
                {
                    "id": suite.id,
                    "name": suite.name,
                    "slug": suite.slug,
                    "latest_run": RunSummarySerializer(latest).data if latest else None,
                }
            )
        return result
