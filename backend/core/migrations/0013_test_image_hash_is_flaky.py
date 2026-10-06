from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_recompute_test_baseline_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="test",
            name="image_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="test",
            name="is_flaky",
            field=models.BooleanField(default=False),
        ),
    ]
