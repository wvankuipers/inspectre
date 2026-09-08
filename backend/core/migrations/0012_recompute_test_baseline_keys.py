# Data migration: recompute `key` on every existing Test and Baseline row
# using the fixed formula from Test._compute_key (slugify each field
# independently, join with "--"). Before this fix, keys were built by
# slugify()-ing one big space-joined string, which could collide across
# different browser/size splits. Without this backfill, rows saved before
# the code fix would keep the old-format key forever (nothing else re-saves
# them), silently diverging from the new-format key computed for anything
# saved after deploy — forking baselines/history for otherwise-identical
# tests.
#
# Known, accepted edge case: if two variants already collided under the old
# buggy key and share a single Baseline row today, this migration cannot
# retroactively create a second baseline for them — one of the two variants
# will end up without a baseline after this runs. That's the correct outcome
# given the data that exists, not a bug in this migration.

from django.db import migrations
from django.utils.text import slugify


def _key(*parts):
    return "--".join(slugify(part) for part in parts)[:512]


def recompute_keys(apps, schema_editor):
    Test = apps.get_model("core", "Test")
    Baseline = apps.get_model("core", "Baseline")

    for test in Test.objects.select_related("run__suite__project").iterator():
        suite = test.run.suite
        new_key = _key(suite.project.name, suite.name, test.name, test.browser, test.size)
        if new_key != test.key:
            test.key = new_key
            test.save(update_fields=["key"])

    for baseline in Baseline.objects.select_related("suite__project").iterator():
        suite = baseline.suite
        new_key = _key(suite.project.name, suite.name, baseline.name, baseline.browser, baseline.size)
        if new_key != baseline.key:
            baseline.key = new_key
            baseline.save(update_fields=["key"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_test_processing_claim"),
    ]

    operations = [
        migrations.RunPython(recompute_keys, noop_reverse),
    ]
