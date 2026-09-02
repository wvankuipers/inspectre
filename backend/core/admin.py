from botocore.exceptions import ClientError
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.db import models as db_models
from django.template.response import TemplateResponse
from django.utils import timezone

from core.models import Baseline, ProcessingQueueTest, Project, Run, Suite, Test
from core.services.s3 import get_s3_client, staging_key_for_test
from core.tasks import process_test


class RenameWarningMixin:
    """Banner on the change form when editing the `name` of a Project or Suite.

    decisions.md #4: renaming re-slugs the model, which changes every contained
    Test's `key` on next ingest and severs the link to existing Baselines.
    Banner makes that visible before save instead of being a silent
    "what just happened to my data" moment.
    """

    change_form_template = "admin/core/rename_warning_change_form.html"

    def render_change_form(self, request, context, *args, **kwargs):
        # Only show on edit, not on add (no existing baselines to sever yet).
        context["show_rename_warning"] = context.get("original") is not None
        return super().render_change_form(request, context, *args, **kwargs)


@admin.register(Project)
class ProjectAdmin(RenameWarningMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "suite_count", "created_at")
    search_fields = ("name", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")  # slug auto-derived from name

    @admin.display(description="Suites")
    def suite_count(self, obj):
        return obj.suites.count()


@admin.register(Suite)
class SuiteAdmin(RenameWarningMixin, admin.ModelAdmin):
    list_display = ("name", "project", "slug", "next_run_seq", "created_at")
    list_filter = ("project",)
    search_fields = ("name", "slug")
    readonly_fields = ("slug", "next_run_seq", "created_at", "updated_at")


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("sequential_id", "suite", "project_name", "test_count", "created_at")
    list_filter = ("suite__project", "suite")
    search_fields = ("suite__name", "suite__project__name")
    readonly_fields = ("sequential_id", "created_at", "updated_at")
    ordering = ("-id",)

    @admin.display(description="Project", ordering="suite__project__name")
    def project_name(self, obj):
        return obj.suite.project.name

    @admin.display(description="Tests")
    def test_count(self, obj):
        return obj.tests.count()


class _URLFieldHttps(forms.URLField):
    # Opt into Django 6 URLField behaviour: assume https when no scheme given.
    # Silences RemovedInDjango60Warning without relying on undocumented
    # formfield_overrides kwarg-forwarding behaviour.
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("assume_scheme", "https")
        super().__init__(*args, **kwargs)


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    formfield_overrides = {db_models.URLField: {"form_class": _URLFieldHttps}}
    list_display = ("name", "browser", "size", "passed", "diff_pct", "run_label", "created_at")
    list_filter = ("passed", "browser", "run__suite__project")
    search_fields = ("name", "key", "run__suite__name", "run__suite__project__name")
    readonly_fields = (  # computed by the diff pipeline; never hand-edit
        "key",
        "diff",
        "passed",
        "screenshot",
        "screenshot_baseline",
        "screenshot_diff",
        "screenshot_thumb",
        "screenshot_baseline_thumb",
        "screenshot_diff_thumb",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": ("run", "name", "browser", "size", "source_url"),
            },
        ),
        (
            "Diff parameters",
            {
                "fields": ("fuzz_level", "highlight_colour", "crop_area"),
                "description": (
                    "Editing these does NOT re-run the diff. To rebaseline, use the "
                    '"Set as baseline" button on the run page or delete the Baseline row.'
                ),
            },
        ),
        (
            "Result (read-only)",
            {
                "fields": ("passed", "diff", "key"),
            },
        ),
        (
            "Files (read-only)",
            {
                "classes": ("collapse",),
                "fields": (
                    "screenshot",
                    "screenshot_baseline",
                    "screenshot_diff",
                    "screenshot_thumb",
                    "screenshot_baseline_thumb",
                    "screenshot_diff_thumb",
                ),
            },
        ),
    )

    @admin.display(description="Diff", ordering="diff")
    def diff_pct(self, obj):
        return f"{obj.diff:.2f}%" if obj.diff else "0%"

    @admin.display(description="Run")
    def run_label(self, obj):
        return f"{obj.run.suite.project.name} / {obj.run.suite.name} #{obj.run.sequential_id}"


@admin.register(ProcessingQueueTest)
class ProcessingQueueAdmin(admin.ModelAdmin):
    list_display = ("name", "browser", "size", "status", "process_attempts", "run_label", "waiting_since", "created_at")
    list_filter = ("status", "browser", "run__suite__project")
    search_fields = ("name", "run__suite__name", "run__suite__project__name")
    ordering = ("created_at",)  # oldest first — front of the queue
    list_select_related = ("run__suite__project", "run__suite")
    actions = ["restart_processing", "discard_from_queue"]

    @admin.action(description="Restart processing")
    def restart_processing(self, request, queryset):
        """Manually re-enqueue stuck pending/processing rows (e.g. after a
        worker crash left the queue stuck). Safe because `process_test` only
        deletes the staged upload in its `finally` block once it actually runs
        to completion (success or failure) — a row stuck here in pending/processing
        never got that far, so its staged upload is still sitting in S3, unless
        its status changed between page load and running this action.
        """
        restarted = 0
        missing = 0
        s3_client = get_s3_client()
        for test in queryset:
            staging_key = staging_key_for_test(test.id)
            try:
                s3_client.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key)
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    missing += 1
                    continue
                raise

            test.status = Test.STATUS_PENDING
            test.process_attempts = 0
            test.save(update_fields=["status", "process_attempts"])
            process_test.delay(test.id, staging_key)
            restarted += 1

        if restarted:
            self.message_user(request, f"Restarted {restarted} test(s).")
        if missing:
            self.message_user(
                request,
                f"{missing} test(s) had no staged upload left in S3 and could not be restarted; re-run them from CI.",
                level=messages.WARNING,
            )
        if not restarted and not missing:
            self.message_user(request, "No queued tests to restart.", level=messages.WARNING)

    @admin.action(description="Discard from queue")
    def discard_from_queue(self, request, queryset):
        """Permanently remove selected rows and their orphaned staged S3 upload.

        Two-step confirm, like Django's built-in "Delete selected" — but skips
        `get_deleted_objects`'s cascade/permission check, since that would
        evaluate `has_delete_permission` against this deliberately locked-down
        ModelAdmin and always report "no permission". Safe to skip: `Test` has
        no meaningful cascade (`Baseline.test` is SET_NULL).

        A missing staged upload (S3 404) is not an error — nothing to clean up,
        so the row is still discarded. Any other S3 error aborts the whole
        action before any row is deleted, rather than discarding a row without
        actually cleaning up its upload.
        """
        if request.POST.get("post") == "yes":
            s3_client = get_s3_client()
            for test in queryset:
                try:
                    s3_client.delete_object(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=staging_key_for_test(test.id),
                    )
                except ClientError as exc:
                    if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                        continue
                    raise
            count = queryset.count()
            queryset.delete()
            self.message_user(request, f"Discarded {count} test(s) from the queue.")
            return None

        context = {
            **self.admin_site.each_context(request),
            "title": "Discard from queue?",
            "queryset": queryset,
            "opts": self.model._meta,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/core/discard_from_queue_confirmation.html", context)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(status__in=[Test.STATUS_PENDING, Test.STATUS_PROCESSING])

    @admin.display(description="Run")
    def run_label(self, obj):
        return f"{obj.run.suite.project.name} / {obj.run.suite.name} #{obj.run.sequential_id}"

    @admin.display(description="Waiting")
    def waiting_since(self, obj):
        delta = timezone.now() - obj.created_at
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes, seconds = divmod(total_seconds, 60)
        if minutes < 60:
            return f"{minutes}m"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"


@admin.register(Baseline)
class BaselineAdmin(admin.ModelAdmin):
    list_display = ("name", "browser", "size", "suite", "has_screenshot", "created_at")
    list_filter = ("suite__project", "suite")
    search_fields = ("name", "key")
    readonly_fields = ("key", "screenshot", "thumbnail", "test", "created_at", "updated_at")

    @admin.display(boolean=True, description="File present")
    def has_screenshot(self, obj):
        return bool(obj.screenshot)
