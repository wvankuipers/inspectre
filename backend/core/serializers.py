from django.db.models import Count, Q
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


def build_run_counts(run_ids, baselined_keys):
    """Batch passing/failing/unbaselined counts for a set of runs into one dict.

    Two GROUP BY queries total, regardless of len(run_ids) — replaces the
    3-queries-per-run pattern in RunSummarySerializer. Every id in `run_ids`
    is guaranteed to be a key in the result (defaulting to zeros), so this
    dict is always dense over its input, never sparse.
    """
    if not run_ids:
        return {}
    counts = {run_id: {"passing": 0, "failing": 0, "unbaselined": 0} for run_id in run_ids}
    for row in (
        Test.objects.filter(run_id__in=run_ids)
        .values("run_id")
        .annotate(passing=Count("id", filter=Q(passed=True)), failing=Count("id", filter=Q(passed=False)))
    ):
        counts[row["run_id"]]["passing"] = row["passing"]
        counts[row["run_id"]]["failing"] = row["failing"]
    for row in (
        Test.objects.filter(run_id__in=run_ids).exclude(key__in=baselined_keys).values("run_id").annotate(n=Count("id"))
    ):
        counts[row["run_id"]]["unbaselined"] = row["n"]
    return counts


class TestRowSerializer(serializers.ModelSerializer):
    """One row in the run-detail table: status, three thumbnails, three full-size URLs.

    `is_baseline_source` is True when this test is the producer of the current
    Baseline for its key. Resolved via context['baseline_source_ids'] populated
    by RunDetailSerializer to avoid N+1 queries.

    `has_baseline` — not `is_baseline_source` — is what drives the SPA's "New
    baseline" chip. It means "does any Baseline exist for this key at all,"
    which stays true even after supersession (mirrors
    RunSummarySerializer.to_representation's definition).
    """

    passed = serializers.BooleanField()
    is_baseline_source = serializers.SerializerMethodField()
    has_baseline = serializers.SerializerMethodField()
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
            "has_baseline",
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

    def get_has_baseline(self, obj):
        # Use pre-fetched keys from context when available (set by RunDetailSerializer.get_tests
        # / serialize_tests_bulk to avoid N+1 queries). Falls back to a direct query for
        # standalone use. Must check `is None`, not falsiness — an empty set (a suite with zero
        # baselines) is a legitimate pre-fetched value and must not trigger the fallback query
        # (see RunSummarySerializer.to_representation for the same fix).
        baselined_keys = self.context.get("baselined_keys")
        if baselined_keys is None:
            baselined_keys = set(Baseline.objects.filter(suite_id=obj.run.suite_id).values_list("key", flat=True))
        return obj.key in baselined_keys

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


class TestHistoryEntrySerializer(serializers.ModelSerializer):
    """One row in a test's cross-run history: the immutable original_passed result,
    not the mutable passed field (which baseline promotion can flip).
    """

    run_sequential_id = serializers.SerializerMethodField()
    run_created_at = serializers.SerializerMethodField()
    screenshot_thumb_url = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            "id",
            "run_id",
            "run_sequential_id",
            "run_created_at",
            "original_passed",
            "is_new_baseline",
            "status",
            "screenshot_thumb_url",
        ]

    def get_run_sequential_id(self, obj):
        return obj.run.sequential_id

    def get_run_created_at(self, obj):
        return obj.run.created_at

    def get_screenshot_thumb_url(self, obj):
        return _file_url(obj.screenshot_thumb)


def serialize_test_history(tests, key):
    """Serialize one test key's ordered history of Test rows (newest run first)."""
    first = tests[0]
    return {
        "key": key,
        "name": first.name,
        "browser": first.browser,
        "size": first.size,
        "project_name": first.run.suite.project.name,
        "suite_slug": first.run.suite.slug,
        "runs": TestHistoryEntrySerializer(tests, many=True).data,
    }


def serialize_tests_bulk(tests):
    """Serialize an arbitrary set of Test rows (may span multiple suites/runs).

    Mirrors RunDetailSerializer.get_tests's baseline-source resolution, but
    grouped per suite since the input isn't guaranteed to be one suite.
    """
    tests = list(tests)
    suite_ids = {t.run.suite_id for t in tests}
    baseline_source_ids = set(
        Baseline.objects.filter(suite_id__in=suite_ids, test_id__isnull=False).values_list("test_id", flat=True)
    )
    baselined_keys = set(Baseline.objects.filter(suite_id__in=suite_ids).values_list("key", flat=True))
    return TestRowSerializer(
        tests,
        many=True,
        context={"baseline_source_ids": baseline_source_ids, "baselined_keys": baselined_keys},
    ).data


class RunSummarySerializer(serializers.ModelSerializer):
    """One row in the suite page's `Latest runs` table — counts only, no test list."""

    passing = serializers.SerializerMethodField()
    failing = serializers.SerializerMethodField()
    unbaselined = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ["id", "sequential_id", "created_at", "passing", "failing", "unbaselined"]

    def to_representation(self, instance):
        # Fast path: counts were pre-batched across many runs by SuiteDetailSerializer /
        # ProjectSerializer (see build_run_counts) — zero extra queries here.
        run_counts = self.context.get("run_counts")
        if run_counts is not None and instance.id in run_counts:
            self._counts = run_counts[instance.id]
        else:
            # Standalone fallback: one query for (passed, key) rows plus, if not already
            # pre-fetched via context (must check `is None`, not falsiness — an empty set is
            # a legitimate pre-fetched value), one query for baseline keys — instead of three
            # separate .count() queries. order_by() clears Test.Meta.ordering, which would
            # otherwise sort by created_at for no reason on a pure counting query. Counts are
            # derived in a single streaming pass rather than three passes over a materialized list.
            baselined_keys = self.context.get("baselined_keys")
            if baselined_keys is None:
                baselined_keys = set(Baseline.objects.filter(suite_id=instance.suite_id).values_list("key", flat=True))
            counts = {"passing": 0, "failing": 0, "unbaselined": 0}
            for passed, key in instance.tests.order_by().values_list("passed", "key"):
                counts["passing" if passed else "failing"] += 1
                if key not in baselined_keys:
                    counts["unbaselined"] += 1
            self._counts = counts
        return super().to_representation(instance)

    def get_passing(self, obj):
        return self._counts["passing"]

    def get_failing(self, obj):
        return self._counts["failing"]

    def get_unbaselined(self, obj):
        return self._counts["unbaselined"]


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
        baselined_keys = set(Baseline.objects.filter(suite_id=obj.suite_id).values_list("key", flat=True))
        return TestRowSerializer(
            obj.tests.all(),
            many=True,
            context={"baseline_source_ids": baseline_source_ids, "baselined_keys": baselined_keys},
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
        runs = list(obj.runs.all()[:5])
        # Pre-fetch baseline keys once for the suite so RunSummarySerializer.get_unbaselined
        # doesn't issue one Baseline query per run (same pattern as RunDetailSerializer).
        baselined_keys = set(Baseline.objects.filter(suite_id=obj.pk).values_list("key", flat=True))
        # Batch passing/failing/unbaselined counts for these runs into two GROUP BY queries
        # total, instead of 3 raw .count() queries per run (same pattern as ProjectSerializer).
        run_counts = build_run_counts([run.id for run in runs], baselined_keys)
        return RunSummarySerializer(
            runs, many=True, context={"baselined_keys": baselined_keys, "run_counts": run_counts}
        ).data


class ProjectSerializer(serializers.ModelSerializer):
    """Top-level projects list. One row per (project, suite) — flattened by the view."""

    suites = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "slug", "suites"]

    def get_suites(self, obj):
        suites = list(obj.suites.all())
        # Pre-fetch baseline keys once for the whole project so RunSummarySerializer.
        # get_unbaselined doesn't issue one Baseline query per suite (same pattern as
        # SuiteDetailSerializer.get_latest_runs / RunDetailSerializer.get_tests).
        suite_ids = [suite.id for suite in suites]
        baselined_keys = set(Baseline.objects.filter(suite_id__in=suite_ids).values_list("key", flat=True))
        # Batch passing/failing/unbaselined counts for every suite's latest run into two
        # GROUP BY queries total, instead of 3 raw .count() queries per suite.
        latest_by_suite = {}
        for suite in suites:
            suite_runs = list(suite.runs.all())
            latest_by_suite[suite.id] = suite_runs[0] if suite_runs else None
        run_counts = build_run_counts([run.id for run in latest_by_suite.values() if run is not None], baselined_keys)
        result = []
        for suite in suites:
            latest = latest_by_suite[suite.id]
            result.append(
                {
                    "id": suite.id,
                    "name": suite.name,
                    "slug": suite.slug,
                    "latest_run": RunSummarySerializer(
                        latest, context={"baselined_keys": baselined_keys, "run_counts": run_counts}
                    ).data
                    if latest
                    else None,
                }
            )
        return result
