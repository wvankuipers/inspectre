"""Flaky-test detection for one freshly diffed Test.

A failure is flaky when the exact same image (by pixel signature) already failed
in an earlier run of the same test key, and the key passed at least once after
that earlier failure — i.e. the test flip-flops between a passing render and a
known bad one. A persistent regression (same image failing run after run with no
pass in between) is a real failure, not a flake.
"""

from core.models import Test


def is_flaky(test: Test) -> bool:
    if test.original_passed is not False or not test.image_hash:
        return False
    prior = Test.objects.filter(
        key=test.key,
        run__suite_id=test.run.suite_id,
        run__sequential_id__lt=test.run.sequential_id,
        status=Test.STATUS_DONE,
    )
    first_match = (
        prior.filter(original_passed=False, is_new_baseline=False, image_hash=test.image_hash)
        .order_by("run__sequential_id")
        .select_related("run")
        .first()
    )
    if first_match is None:
        return False
    return prior.filter(original_passed=True, run__sequential_id__gt=first_match.run.sequential_id).exists()
