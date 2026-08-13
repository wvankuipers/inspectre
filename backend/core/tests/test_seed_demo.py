"""Integration test for the seed_demo management command.

Lives in the slow pack because every passing/failing Test drives the real
ImageMagick `compare` pipeline through ScreenshotComparison.
"""

import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Baseline, Project, Run, Suite, Test


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_seed_demo_creates_four_projects():
    call_command("seed_demo", yes=True)
    assert Project.objects.count() == 4


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_seed_demo_is_idempotent(settings):
    """Re-running seed_demo wipes existing Test rows, which now fires the
    pre_delete signal's async S3 cleanup enqueue for real. Force Celery
    eager mode so the task runs inline instead of requiring a live broker.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    call_command("seed_demo", yes=True)
    first = (
        Project.objects.count(),
        Suite.objects.count(),
        Run.objects.count(),
        Test.objects.count(),
        Baseline.objects.count(),
    )
    call_command("seed_demo", yes=True)
    second = (
        Project.objects.count(),
        Suite.objects.count(),
        Run.objects.count(),
        Test.objects.count(),
        Baseline.objects.count(),
    )
    assert first == second, f"Re-running changed counts: {first} → {second}"


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_seed_demo_attaches_real_screenshots():
    """At least one passing test, one failing test, and one no-baseline
    test exist after seeding, with the file shapes you'd expect from each.
    """
    call_command("seed_demo", yes=True)

    # A passing test from run 2+ (not the first upload for a key) will have
    # performed a real comparison and thus have a baseline screenshot.
    passing = (
        Test.objects.filter(passed=True, run__suite__project__name="Acme Marketing Site")
        .exclude(screenshot="")
        .exclude(run__sequential_id=1)
        .first()
    )
    assert passing is not None, "no passing test with a screenshot found in run 2+"
    assert passing.screenshot_baseline, "passing test should have a baseline screenshot"
    assert passing.screenshot_thumb, "passing test should have a thumbnail"

    failing = Test.objects.filter(passed=False).exclude(screenshot_diff="").first()
    assert failing is not None, "no failing test with a diff image found"
    assert failing.screenshot_diff.size > 0, "diff file should be non-empty"

    no_baseline = Test.objects.filter(name="new_unbaselined_page").first()
    assert no_baseline is not None, "expected a test named 'new_unbaselined_page'"
    assert no_baseline.screenshot, "no-baseline test should still have a screenshot"
    assert not no_baseline.screenshot_baseline, "no-baseline test must not have a baseline screenshot attached"
    assert no_baseline.passed is False


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_seed_demo_dataset_shape():
    call_command("seed_demo", yes=True)

    names = sorted(Project.objects.values_list("name", flat=True))
    assert names == ["Acme Marketing Site", "Empty Project", "Inspectre Internal", "New Feature Branch"]

    acme = Project.objects.get(name="Acme Marketing Site")
    assert sorted(acme.suites.values_list("name", flat=True)) == [
        "Desktop",
        "Mobile",
        "Tablet",
    ]
    assert acme.suites.get(name="Desktop").runs.count() == 5
    assert acme.suites.get(name="Mobile").runs.count() == 5
    assert acme.suites.get(name="Tablet").runs.count() == 0

    inspectre = Project.objects.get(name="Inspectre Internal")
    dashboard = inspectre.suites.get(name="Dashboard")
    assert dashboard.runs.count() == 3
    assert inspectre.suites.count() == 1

    empty = Project.objects.get(name="Empty Project")
    assert empty.suites.count() == 0


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_seed_demo_backdates_run_timestamps():
    call_command("seed_demo", yes=True)

    desktop = Suite.objects.get(project__name="Acme Marketing Site", name="Desktop")
    runs = list(desktop.runs.order_by("created_at"))
    assert len(runs) == 5

    # Oldest run is at least ~12 days old; newest is within today.
    age_days = (timezone.now() - runs[0].created_at).days
    assert age_days >= 12, f"oldest Acme/Desktop run only {age_days} days old"
    newest_age = timezone.now() - runs[-1].created_at
    assert newest_age < dt.timedelta(days=1), f"newest Acme/Desktop run is {newest_age} old; expected <1 day"
