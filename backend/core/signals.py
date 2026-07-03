import logging

from django.conf import settings
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Run, Test

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Run)
def purge_old_runs(sender, instance, created, **kwargs):
    """Keep only RUN_RETENTION_PER_SUITE runs per suite; cascade-delete the rest.

    Default 5 (decisions.md #1; legacy parity). Configurable via env.
    Gated on `created=True` so updates to a Run don't fire the purge.
    """
    if not created:
        return

    retain = settings.RUN_RETENTION_PER_SUITE
    stale_ids = list(
        Run.objects.filter(suite_id=instance.suite_id).order_by("-id").values_list("pk", flat=True)[retain:]
    )
    if stale_ids:
        Run.objects.filter(pk__in=stale_ids).delete()
        logger.info(
            "purged old runs",
            extra={
                "suite_id": instance.suite_id,
                "purged": len(stale_ids),
                "retained": retain,
            },
        )


_TEST_FILE_FIELDS = [
    "screenshot",
    "screenshot_baseline",
    "screenshot_diff",
    "screenshot_thumb",
    "screenshot_baseline_thumb",
    "screenshot_diff_thumb",
]


@receiver(pre_delete, sender=Test)
def delete_test_files(sender, instance, **kwargs):
    """Remove S3/storage files when a Test row is deleted (including cascade deletes)."""
    for field_name in _TEST_FILE_FIELDS:
        field = getattr(instance, field_name)
        if field:
            field.delete(save=False)
