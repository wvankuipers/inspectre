from django import forms
from django.contrib import admin
from django.db import models as db_models
from django.utils import timezone

from core.models import Baseline, ProcessingQueueTest, Project, Run, Suite, Test


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
    list_display = ("name", "browser", "size", "status", "run_label", "waiting_since", "created_at")
    list_filter = ("status", "browser", "run__suite__project")
    search_fields = ("name", "run__suite__name", "run__suite__project__name")
    ordering = ("created_at",)  # oldest first — front of the queue
    list_select_related = ("run__suite__project", "run__suite")

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
