import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Run, Test
from .tasks import delete_test_file_keys

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
    """Enqueue async deletion of a Test's S3/storage files.

    Runs on pre_delete (including cascade deletes, e.g. deleting a Project
    from admin) so file names are still available before the row is gone.
    Deletion itself is deferred to a Celery task, and the enqueue is
    deferred to transaction.on_commit, so a large cascade delete never
    blocks the request on synchronous S3 calls, and a rolled-back
    transaction never triggers deletion of files that still exist.
    """
    keys = [name for field_name in _TEST_FILE_FIELDS if (name := getattr(instance, field_name).name)]
    if not keys:
        return
    transaction.on_commit(lambda: delete_test_file_keys.delay(keys))
