import pytest

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
# These literals pin the wire format. Updating one is a wire-format change;
# review carefully.

LEGACY_RUN_FIELDS = frozenset(
    {
        "id",
        "suite_id",
        "sequential_id",
        "created_at",
        "updated_at",
        "url",
    }
)

LEGACY_TEST_FIELDS = frozenset(
    {
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
        "pass",
        "source_url",
        "fuzz_level",
        "highlight_colour",
        "crop_area",
        "created_at",
        "updated_at",
        "url",
        "status",
    }
)

LEGACY_BASELINE_FIELDS = frozenset(
    {
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
    }
)


# ---- The single most important assertion in this file --------------------


def test_legacy_test_serializer_uses_pass_not_passed(test_factory):
    """The wire format is `"pass"`, never `"passed"` or `"pass_field"`.

    This is the regression that breaks every CI pipeline using the legacy API.
    """
    test = test_factory(passed=True)
    body = LegacyTestSerializer(test).data

    assert "pass" in body
    assert body["pass"] is True
    assert "passed" not in body
    assert "pass_field" not in body


def test_legacy_test_serializer_pass_reflects_model_state(test_factory):
    """Both branches of `passed` round-trip correctly to the wire `"pass"` key."""
    passing = test_factory(passed=True)
    failing = test_factory(passed=False)

    assert LegacyTestSerializer(passing).data["pass"] is True
    assert LegacyTestSerializer(failing).data["pass"] is False


# ---- Frozen field-set checks ---------------------------------------------


@pytest.mark.parametrize(
    "serializer_cls,factory_name,expected_fields",
    [
        (LegacyRunSerializer, "run_factory", LEGACY_RUN_FIELDS),
        (LegacyTestSerializer, "test_factory", LEGACY_TEST_FIELDS),
    ],
)
def test_legacy_serializer_field_set_is_frozen(
    serializer_cls,
    factory_name,
    expected_fields,
    request,
):
    """Adding a field to the model must NOT silently appear in the legacy response.

    If this test fails because a new field appeared, ask:
    - Was the field added because the Client API now expects it? Update LEGACY_*_FIELDS.
    - Was it accidental? Remove the field from the legacy serializer's `fields`.
    """
    factory = request.getfixturevalue(factory_name)
    body = serializer_cls(factory()).data
    assert frozenset(body.keys()) == expected_fields


def test_legacy_baseline_serializer_field_set_is_frozen(baseline_factory):
    body = LegacyBaselineSerializer(baseline_factory()).data
    assert frozenset(body.keys()) == LEGACY_BASELINE_FIELDS


# ---- URL shape — survives renames ----------------------------------------


def test_legacy_run_url_uses_current_slug_after_rename(run_factory):
    """LegacyRunSerializer.url reflects the current slug, not the slug at run-creation.

    decisions.md #4: rename re-slugs the project, and the URL should follow.
    """
    run = run_factory()
    run.suite.project.name = "Renamed Project"
    run.suite.project.save()

    body = LegacyRunSerializer(run).data
    assert body["url"].startswith("/projects/renamed-project/suites/")


def test_legacy_test_url_includes_anchor(test_factory):
    test = test_factory()
    body = LegacyTestSerializer(test).data
    assert body["url"].endswith(f"#test_{test.id}")


def test_legacy_test_serializer_includes_status(test_factory):
    test = test_factory()
    body = LegacyTestSerializer(test).data
    assert "status" in body
    assert body["status"] == "pending"


def test_spa_test_row_serializer_includes_status(test_factory):
    body = TestRowSerializer(test_factory()).data
    assert "status" in body
    assert body["status"] == "pending"


# ---- File URLs — None when storage is empty -------------------------------


def test_legacy_test_serializer_uid_fields_are_none_when_no_file(test_factory):
    """Mid-comparison Tests have no attached files yet → uid fields are null, not '/'."""
    body = LegacyTestSerializer(test_factory()).data

    assert body["screenshot_uid"] is None
    assert body["screenshot_baseline_uid"] is None
    assert body["screenshot_diff_uid"] is None


@pytest.mark.parametrize(
    "url_field",
    [
        "screenshot_url",
        "baseline_url",
        "diff_url",
        "screenshot_thumb_url",
        "baseline_thumb_url",
        "diff_thumb_url",
    ],
)
def test_spa_test_row_url_fields_are_none_when_no_file(test_factory, url_field):
    """Same invariant on the SPA side: missing FileFields render as null, not as a broken URL."""
    body = TestRowSerializer(test_factory()).data
    assert body[url_field] is None


# ---- SPA-side latest_runs limit ------------------------------------------


def test_suite_detail_serializer_returns_at_most_5_runs(suite_factory, run_factory, settings):
    """purge_old_runs keeps RUN_RETENTION_PER_SUITE; verify the serializer surfaces them all."""
    settings.RUN_RETENTION_PER_SUITE = 5
    suite = suite_factory()
    for _ in range(8):
        run_factory(suite=suite)

    body = SuiteDetailSerializer(suite).data
    assert len(body["latest_runs"]) == 5


def test_suite_detail_serializer_includes_project_name(suite_factory, project_factory):
    project = project_factory(name="Acme Corp")
    suite = suite_factory(project=project)
    body = SuiteDetailSerializer(suite).data
    assert body["project_name"] == "Acme Corp"


def test_run_detail_serializer_includes_project_name(run_factory, suite_factory, project_factory):
    project = project_factory(name="Acme Corp")
    suite = suite_factory(project=project)
    run = run_factory(suite=suite)
    body = RunDetailSerializer(run).data
    assert body["project_name"] == "Acme Corp"


# ---- SPA wire format — sentinel keys --------------------------------------


@pytest.mark.parametrize(
    "serializer_cls,factory_name,expected_key",
    [
        (TestRowSerializer, "test_factory", "passed"),
        (RunDetailSerializer, "run_factory", "tests"),
        (RunSummarySerializer, "run_factory", "sequential_id"),
    ],
)
def test_spa_serializer_exposes_expected_key(
    serializer_cls,
    factory_name,
    expected_key,
    request,
):
    """Smoke test that each SPA serializer still exposes its identity-defining key.

    A failure here usually means a model field was renamed and the serializer
    `fields` list wasn't updated.
    """
    instance = request.getfixturevalue(factory_name)()
    body = serializer_cls(instance).data
    assert expected_key in body


def test_baseline_serializer_exposes_thumbnail_url(baseline_factory):
    body = BaselineSerializer(baseline_factory()).data
    assert "thumbnail_url" in body


# ---- SPA wire format — uses `passed`, never the legacy `pass` ------------


def test_spa_test_row_uses_passed_not_pass(test_factory):
    """The SPA's wire format uses `passed`; the legacy API wire format uses `pass`.

    api.md, "Serializers": SPA serializers expose the model field name.
    """
    body = TestRowSerializer(test_factory(passed=True)).data

    assert "passed" in body
    assert body["passed"] is True
    assert "pass" not in body, "leaked the legacy wire format into the SPA payload"


# ---- ProjectSerializer flattens suites -----------------------------------


def test_project_serializer_includes_suites(project_factory, suite_factory, run_factory):
    project = project_factory(name="Acme")
    suite_factory(project=project, name="Desktop")
    suite_factory(project=project, name="Mobile")

    body = ProjectSerializer(project).data
    suite_names = {s["name"] for s in body["suites"]}
    assert suite_names == {"Desktop", "Mobile"}


def test_project_serializer_suite_with_no_runs_has_null_latest_run(
    project_factory,
    suite_factory,
):
    """The legacy template crashed when suite.latest_run was nil. The SPA gets a clean null."""
    project = project_factory()
    suite_factory(project=project)

    body = ProjectSerializer(project).data
    assert body["suites"][0]["latest_run"] is None


def test_project_serializer_suite_with_runs_includes_latest_run_summary(
    project_factory,
    suite_factory,
    run_factory,
):
    project = project_factory()
    suite = suite_factory(project=project)
    run_factory(suite=suite)
    run_factory(suite=suite)

    body = ProjectSerializer(project).data
    assert body["suites"][0]["latest_run"]["sequential_id"] == 2


# ---- RunSummarySerializer.unbaselined ------------------------------------


def test_run_summary_unbaselined_counts_tests_with_no_baseline(suite_factory, run_factory, baseline_factory):
    """Tests whose key is absent from the suite's Baseline table count as unbaselined."""
    from core.models import Test

    suite = suite_factory()
    run = run_factory(suite=suite)
    # Create two tests with distinct keys
    t1 = Test.objects.create(run=run, name="home", browser="Chrome", size="1024")
    Test.objects.create(run=run, name="about", browser="Chrome", size="1024")
    # Baseline only t1's key
    baseline_factory(suite=suite, key=t1.key)

    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 1  # t2 has no baseline


def test_run_summary_unbaselined_is_zero_when_all_baselined(suite_factory, run_factory, baseline_factory):
    """Zero when every test key has a matching Baseline."""
    from core.models import Test

    suite = suite_factory()
    run = run_factory(suite=suite)
    t1 = Test.objects.create(run=run, name="home", browser="Chrome", size="1024")
    baseline_factory(suite=suite, key=t1.key)

    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 0


def test_run_summary_unbaselined_is_zero_when_run_has_no_tests(run_factory):
    """Runs with no tests at all return unbaselined == 0, not an error."""
    run = run_factory()
    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 0
