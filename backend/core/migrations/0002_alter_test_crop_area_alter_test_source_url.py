# DJ001 fix, step 1: coerce NULL → '' on existing rows so the next migration
# can safely drop the nullability constraint.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "UPDATE core_test SET crop_area = '' WHERE crop_area IS NULL;",
                "UPDATE core_test SET source_url = '' WHERE source_url IS NULL;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
