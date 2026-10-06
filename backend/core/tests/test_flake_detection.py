import pytest

from core.models import Test
from core.services.flake_detection import is_flaky

pytestmark = pytest.mark.django_db

BAD = "b" * 64
GOOD = "a" * 64


@pytest.fixture
def history(suite_factory, run_factory, test_factory):
    """Build a sequence of completed runs for one test key in one suite.

    history([("fail", BAD), ("pass", GOOD), ...]) returns the created Test rows
    in run order. "new" = a first upload (original_passed=False, is_new_baseline=True).
    """
    suite = suite_factory()

    def _make(steps, name="Homepage", suite=suite):
        rows = []
        for outcome, image_hash in steps:
            run = run_factory(suite=suite)
            rows.append(
                test_factory(
                    run=run,
                    name=name,
                    status=Test.STATUS_DONE,
                    original_passed=(outcome == "pass"),
                    passed=(outcome == "pass"),
                    is_new_baseline=(outcome == "new"),
                    image_hash=image_hash,
                )
            )
        return rows

    return _make


def _current(test_factory, run_factory, suite, image_hash=BAD, name="Homepage", passed=False):
    """The test being judged: just diffed, still `processing` (as inside the pipeline)."""
    return test_factory(
        run=run_factory(suite=suite),
        name=name,
        status=Test.STATUS_PROCESSING,
        original_passed=passed,
        passed=passed,
        image_hash=image_hash,
    )


def test_no_prior_runs_is_not_flaky(test_factory, run_factory, suite_factory):
    current = _current(test_factory, run_factory, suite_factory())
    assert is_flaky(current) is False


def test_fail_pass_fail_same_image_is_flaky(history, test_factory, run_factory):
    rows = history([("new", GOOD), ("fail", BAD), ("pass", GOOD)])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is True


def test_persistent_failure_without_pass_in_between_is_not_flaky(history, test_factory, run_factory):
    rows = history([("new", GOOD), ("pass", GOOD), ("fail", BAD)])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is False


def test_recurrence_after_earlier_pass_is_flaky_even_if_last_run_failed(history, test_factory, run_factory):
    # B, A, B, (B) — the image recurred after a pass, so it flip-flops.
    rows = history([("fail", BAD), ("pass", GOOD), ("fail", BAD)])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is True


def test_different_failing_image_is_not_flaky(history, test_factory, run_factory):
    rows = history([("fail", "c" * 64), ("pass", GOOD)])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is False


def test_prior_first_upload_with_same_image_does_not_count(history, test_factory, run_factory):
    rows = history([("new", BAD), ("pass", GOOD)])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is False


def test_prior_pipeline_failure_is_ignored(history, test_factory, run_factory):
    rows = history([("fail", BAD), ("pass", GOOD)])
    rows[0].status = Test.STATUS_FAILED
    rows[0].save(update_fields=["status"])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is False


def test_prior_still_processing_run_is_ignored(history, test_factory, run_factory):
    rows = history([("fail", BAD), ("pass", GOOD)])
    rows[0].status = Test.STATUS_PROCESSING
    rows[0].save(update_fields=["status"])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is False


def test_other_test_key_is_ignored(history, test_factory, run_factory):
    rows = history([("fail", BAD), ("pass", GOOD)], name="Other page")
    current = _current(test_factory, run_factory, rows[0].run.suite, name="Homepage")
    assert is_flaky(current) is False


def test_other_suite_is_ignored(history, test_factory, run_factory, suite_factory):
    history([("fail", BAD), ("pass", GOOD)])
    current = _current(test_factory, run_factory, suite_factory())
    assert is_flaky(current) is False


def test_passing_current_test_is_never_flaky(history, test_factory, run_factory):
    rows = history([("fail", BAD), ("pass", GOOD)])
    current = _current(test_factory, run_factory, rows[0].run.suite, passed=True)
    assert is_flaky(current) is False


def test_missing_hash_is_never_flaky(history, test_factory, run_factory):
    rows = history([("fail", ""), ("pass", GOOD)])
    current = _current(test_factory, run_factory, rows[0].run.suite, image_hash="")
    assert is_flaky(current) is False


def test_promoted_prior_failure_still_counts(history, test_factory, run_factory):
    # "Set as baseline" flips passed=True but original_passed stays False.
    rows = history([("fail", BAD), ("pass", GOOD)])
    rows[0].passed = True
    rows[0].save(update_fields=["passed"])
    current = _current(test_factory, run_factory, rows[0].run.suite)
    assert is_flaky(current) is True


def test_later_runs_are_ignored(history, test_factory, run_factory, suite_factory):
    # Reprocessing run #1 must not look at runs #2/#3 that came after it.
    suite = suite_factory()
    current = _current(test_factory, run_factory, suite)
    history([("fail", BAD), ("pass", GOOD)], suite=suite)
    assert is_flaky(current) is False
