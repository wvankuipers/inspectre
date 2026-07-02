# DJ001 fix, step 2: now that NULLs are gone, drop the nullability.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alter_test_crop_area_alter_test_source_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='test',
            name='crop_area',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AlterField(
            model_name='test',
            name='source_url',
            field=models.URLField(blank=True, default='', max_length=2048),
        ),
    ]
