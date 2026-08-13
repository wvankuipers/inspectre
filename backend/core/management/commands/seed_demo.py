"""Seed deterministic demo data for manual UI testing.

Wipes any existing project/suite/run/test/baseline rows and the demo
storage prefixes, then rebuilds four projects covering healthy
multi-suite navigation, mixed pass/fail history, empty-state and
unbaselined edge cases.
"""

import logging
import random
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Baseline, Project, Run, Suite, Test
from core.services.baseline_upsert import upsert_baseline_from_test
from core.services.screenshot_comparison import ScreenshotComparison

logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(settings.BASE_DIR) / "core" / "tests" / "fixtures" / "images"
PASS_IMAGE = FIXTURE_DIR / "run1.png"
FAIL_IMAGE = FIXTURE_DIR / "run2.png"

# Six tests per run, same names across runs so per-key history is stable.
TEST_NAMES = ["homepage", "pricing", "signup", "dashboard", "settings", "about"]
# Browser/size variants cycle so each run has a mix.
VARIANTS = [("Chrome", "1024"), ("Chrome", "1440"), ("Firefox", "1024")]
# Five Acme runs across the last two weeks.
ACME_RUN_OFFSETS_DAYS = [13, 10, 7, 3, 0]
# Three Inspectre Internal runs.
INSPECTRE_RUN_OFFSETS_DAYS = [10, 5, 0]


class Command(BaseCommand):
    help = "Wipe and reseed demo data for manual UI testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirm destructive wipe. Required when DEBUG is False.",
        )

    def handle(self, *args, **options):
        if not options["yes"] and not settings.DEBUG:
            raise CommandError("This command wipes all data. Pass --yes to confirm, or run with DEBUG=True.")
        rng = random.Random(42)
        self._wipe()
        self._seed_acme(rng)
        self._seed_inspectre_internal()
        self._seed_empty()
        self._seed_unbaselined()
        self.stdout.write(self.style.SUCCESS("Demo data seeded."))

    # ---- wipe -------------------------------------------------------------

    def _wipe(self) -> None:
        """Drop demo rows and sweep object storage.

        Order: Test → Run → Baseline → Suite → Project. Cascades would
        cover most of this; explicit ordering keeps intent obvious.
        Auth/admin tables are untouched.
        """
        with transaction.atomic():
            Test.objects.all().delete()
            Run.objects.all().delete()
            Baseline.objects.all().delete()
            Suite.objects.all().delete()
            Project.objects.all().delete()

        for prefix in ("screenshots/", "baselines/"):
            self._sweep_storage(prefix)

    def _sweep_storage(self, prefix: str) -> None:
        try:
            dirs, files = default_storage.listdir(prefix)
        except FileNotFoundError:
            return
        for name in files:
            default_storage.delete(prefix + name)
        for sub in dirs:
            self._sweep_storage(prefix + sub + "/")

    # ---- per-project seeders ---------------------------------------------

    def _seed_acme(self, rng: random.Random) -> None:
        """Healthy multi-suite project. 2 suites with runs across 14 days,
        plus a third suite with no runs to exercise the empty-suite UI.
        """
        project = Project.objects.create(name="Acme Marketing Site")
        desktop = Suite.objects.create(project=project, name="Desktop")
        mobile = Suite.objects.create(project=project, name="Mobile")
        Suite.objects.create(project=project, name="Tablet")  # intentionally no runs

        for suite in (desktop, mobile):
            for idx, days_ago in enumerate(ACME_RUN_OFFSETS_DAYS):
                # First run per suite has nothing to compare against and needs
                # manual approval before later runs can compare against it.
                # Later runs sprinkle 0–2 fails.
                fail_count = 0 if idx == 0 else rng.choice([0, 1, 2])
                fail_indices = set(rng.sample(range(len(TEST_NAMES)), fail_count)) if fail_count else set()
                run = self._create_run(
                    suite,
                    days_ago=days_ago,
                    fail_indices=fail_indices,
                    with_orphan=False,
                )
                if idx == 0:
                    for test in run.tests.all():
                        self._approve_as_baseline(test)

    def _seed_inspectre_internal(self) -> None:
        """Mixed-signal project. Older runs all green; latest run has two
        regressions and one test that has never been baselined.
        """
        project = Project.objects.create(name="Inspectre Internal")
        suite = Suite.objects.create(project=project, name="Dashboard")

        # Older run has nothing to compare against yet — approve its tests so
        # the middle/latest runs have real baselines to compare against.
        oldest_run = self._create_run(
            suite, days_ago=INSPECTRE_RUN_OFFSETS_DAYS[0], fail_indices=set(), with_orphan=False
        )
        for test in oldest_run.tests.all():
            self._approve_as_baseline(test)
        # Middle run: still all green.
        self._create_run(suite, days_ago=INSPECTRE_RUN_OFFSETS_DAYS[1], fail_indices=set(), with_orphan=False)
        # Latest: two regressions + a test with no prior baseline.
        self._create_run(
            suite,
            days_ago=INSPECTRE_RUN_OFFSETS_DAYS[2],
            fail_indices={0, 2},
            with_orphan=True,
        )

    def _seed_empty(self) -> None:
        """Edge case: project with no suites at all."""
        Project.objects.create(name="Empty Project")

    def _seed_unbaselined(self) -> None:
        """Edge case: all tests in the run are first uploads awaiting approval.

        Every test uses _attach_no_baseline, which drives ScreenshotComparison
        against a never-before-seen key so it takes the first-upload path
        (no comparison images, passed=False). This exercises the
        "New baseline, awaiting approval" UI state across an entire run.
        """
        project = Project.objects.create(name="New Feature Branch")
        suite = Suite.objects.create(project=project, name="Staging")
        run = Run.objects.create(suite=suite)
        Run.objects.filter(pk=run.pk).update(created_at=timezone.now(), updated_at=timezone.now())
        for idx, name in enumerate(TEST_NAMES):
            browser, size = VARIANTS[idx % len(VARIANTS)]
            test = Test.objects.create(run=run, name=name, browser=browser, size=size)
            self._attach_no_baseline(test)

    # ---- run + test creation ---------------------------------------------

    def _create_run(
        self,
        suite: Suite,
        *,
        days_ago: int,
        fail_indices: set[int],
        with_orphan: bool,
    ) -> Run:
        """Create one Run and its Tests, then backdate the Run timestamp."""
        run = Run.objects.create(suite=suite)
        when = timezone.now() - timedelta(days=days_ago)
        # Run.created_at is auto_now_add, so update directly via the queryset.
        Run.objects.filter(pk=run.pk).update(created_at=when, updated_at=when)

        for idx, name in enumerate(TEST_NAMES):
            browser, size = VARIANTS[idx % len(VARIANTS)]
            test = Test.objects.create(run=run, name=name, browser=browser, size=size)
            if idx in fail_indices:
                # Establish the baseline for this run, then introduce the
                # regression. On run 2+ the baseline already exists from
                # an earlier run, so the first call is a fast no-op
                # (identical screenshot vs identical baseline). The flow
                # is the same either way, which keeps the helper simple.
                self._attach_passing(test)
                self._attach_failing(test)
            else:
                self._attach_passing(test)

        if with_orphan:
            orphan = Test.objects.create(
                run=run,
                name="new_unbaselined_page",
                browser="Chrome",
                size="1024",
            )
            self._attach_no_baseline(orphan)

        return run

    # ---- image attachment helpers ----------------------------------------

    def _attach_passing(self, test: Test) -> None:
        """Drive the real diff pipeline with PASS_IMAGE.

        Caller must have already established a baseline for this test's key
        (via _approve_as_baseline on an earlier test sharing the key) — otherwise
        this is a first upload with nothing to compare against, and the test
        is stored unapproved (passed=False) rather than passing.
        """
        upload = SimpleUploadedFile(
            "screenshot.png",
            PASS_IMAGE.read_bytes(),
            content_type="image/png",
        )
        ScreenshotComparison(test, upload).run()
        test.status = Test.STATUS_DONE
        test.save(update_fields=["status"])

    def _attach_failing(self, test: Test) -> None:
        """Drive the diff pipeline with FAIL_IMAGE against an existing baseline.

        Caller must have established a baseline for this test's key first
        (typically via `_attach_passing` + `_approve_as_baseline` on an
        earlier-run test that shares the same key). Otherwise this is a first
        upload with nothing to compare against, so the test ends up
        unapproved (passed=False) regardless of image content — not the
        regression state we want to seed.
        """
        upload = SimpleUploadedFile(
            "screenshot.png",
            FAIL_IMAGE.read_bytes(),
            content_type="image/png",
        )
        ScreenshotComparison(test, upload).run()
        test.status = Test.STATUS_DONE
        test.save(update_fields=["status"])

    def _attach_no_baseline(self, test: Test) -> None:
        """Drive the real diff pipeline with FAIL_IMAGE for a key that has
        never been seeded before, so ScreenshotComparison takes its
        first-upload path: screenshot + thumbnail only, no baseline/diff
        images, `passed=False`, awaiting manual approval. The image content
        doesn't matter — there's nothing to compare against regardless of
        which image is used.
        """
        upload = SimpleUploadedFile(
            "screenshot.png",
            FAIL_IMAGE.read_bytes(),
            content_type="image/png",
        )
        ScreenshotComparison(test, upload).run()
        test.status = Test.STATUS_DONE
        test.save(update_fields=["status"])

    def _approve_as_baseline(self, test: Test) -> None:
        """Simulate a human clicking 'Set as baseline' — the manual approval
        step now required before any test's screenshot can serve as the
        reference image for its key. Mirrors _set_as_baseline in views/legacy.py.
        """
        test.passed = True
        test.save(update_fields=["passed"])
        upsert_baseline_from_test(test)
