from django import forms
from django.contrib import admin
from django.db import models as db_models

from core.models import Baseline, Project, Run, Suite, Test


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


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    # Opt into Django 6 URLField behaviour (https as the assumed scheme).
    # Silences RemovedInDjango60Warning that fires when the form is rendered
    # without an explicit assume_scheme argument.
    formfield_overrides = {
        db_models.URLField: {"form_class": forms.URLField, "assume_scheme": "https"},
    }
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


@admin.register(Baseline)
class BaselineAdmin(admin.ModelAdmin):
    list_display = ("name", "browser", "size", "suite", "has_screenshot", "created_at")
    list_filter = ("suite__project", "suite")
    search_fields = ("name", "key")
    readonly_fields = ("key", "screenshot", "thumbnail", "test", "created_at", "updated_at")

    @admin.display(boolean=True, description="File present")
    def has_screenshot(self, obj):
        return bool(obj.screenshot)
