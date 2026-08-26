# Best-effort backfill: existing rows have no record of their diff-pipeline
# result before any baseline promotion may have mutated `passed`, so we copy
# the current (possibly already-promoted) `passed` value as a stand-in.

from django.db import migrations, models


def backfill_original_passed(apps, schema_editor):
    Test = apps.get_model("core", "Test")
    Test.objects.update(original_passed=models.F("passed"))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_test_original_passed'),
    ]

    operations = [
        migrations.RunPython(backfill_original_passed, noop_reverse),
    ]
