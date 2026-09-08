"""Tests for data migrations.

These exercise migration code against Django's *historical* model snapshots
(via `MigrationExecutor`), not the current `core.models` classes. That
distinction matters here: the real `Test.save()` recomputes `key` on every
save via `_compute_key`, which would silently mask a bug in the migration's
independently-reimplemented `_key()` formula. Historical models have no such
override, so running the migration function against them is a genuine test
of the migration's own logic, not of the current model.
"""

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

migration_module = importlib.import_module("core.migrations.0012_recompute_test_baseline_keys")


@pytest.fixture
def historical_apps():
    """The app registry as it existed right after migration 0012 ran, i.e.
    before any later migration (or `core.models`) can influence behaviour.
    """
    executor = MigrationExecutor(connection)
    project_state = executor.loader.project_state(("core", "0012_recompute_test_baseline_keys"))
    return project_state.apps


class TestRecomputeKeysMigration:
    def test_historical_models_have_no_custom_save_or_compute_key(self, historical_apps):
        """Confirms the historical Test/Baseline models are genuinely bare
        (no _compute_key, and save() is the plain Django default) — the
        property that makes this test meaningful at all. If Django's
        historical models ever picked up the real model's methods, this
        test would need to change, and so would our confidence in the
        migration test below.
        """
        historical_test = historical_apps.get_model("core", "Test")
        historical_baseline = historical_apps.get_model("core", "Baseline")

        assert not hasattr(historical_test, "_compute_key")
        assert not hasattr(historical_baseline, "_compute_key")
        # The historical model's save is Django's own, not the subclassed
        # override defined in core.models.Test.
        assert historical_test.save.__qualname__.startswith("Model.save")

    def test_recompute_keys_converts_old_format_keys_to_new_format(
        self, project_factory, suite_factory, run_factory, test_factory, baseline_factory, historical_apps
    ):
        project = project_factory(name="My Project")
        suite = suite_factory(project=project, name="My Suite")
        run = run_factory(suite=suite)
        test = test_factory(run=run, name="Home Page", browser="Chrome", size="1024")
        baseline = baseline_factory(suite=suite, name="Home Page", browser="Chrome", size="1024", key="old-format-key")

        # Force the pre-fix, single-string-slugify key format via .update()
        # to bypass Test.save()'s override (which would immediately
        # recompute the new-format key on any save()).
        old_style_key = "old-format-key"
        type(test).objects.filter(pk=test.pk).update(key=old_style_key)
        type(baseline).objects.filter(pk=baseline.pk).update(key=old_style_key)

        historical_test_model = historical_apps.get_model("core", "Test")
        historical_baseline_model = historical_apps.get_model("core", "Baseline")

        assert historical_test_model.objects.get(pk=test.pk).key == old_style_key
        assert historical_baseline_model.objects.get(pk=baseline.pk).key == old_style_key

        migration_module.recompute_keys(historical_apps, None)

        test.refresh_from_db()
        baseline.refresh_from_db()

        expected_key = "my-project--my-suite--home-page--chrome--1024"
        assert test.key == expected_key
        assert baseline.key == expected_key
        assert test.key == baseline.key
