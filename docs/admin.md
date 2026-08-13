# Admin (`/admin`)

`rails_admin` is mounted at `/admin` with **no authentication** and full CRUD over every model. It's the only way to edit/delete data in Spectre — there are no UI forms or HTTP endpoints for it.

## What's available today

Configured in `config/initializers/rails_admin.rb`:

```ruby
RailsAdmin.config do |config|
  config.actions do
    dashboard
    index
    new
    export
    bulk_delete
    show
    edit
    delete
    show_in_app
  end
end
```

So an admin can:

- Browse and search Project / Suite / Run / Test / Baseline records.
- Create, edit, delete records of all five types (subject to `dependent: :destroy` cascades).
- Bulk-delete via checkboxes.
- Export records (CSV, JSON, XML).
- Click "Show in app" to jump to the front-end view of a record.

## What admins typically use it for

Inferred from gaps in the public UI:

- **Delete a stale baseline** — there's no UI to drop a baseline. Admins delete the row, which forces the next test to self-baseline.
- **Rename a project or suite** — ditto, no UI. Note: editing `name` does **not** update `slug`, and changing the slug breaks all existing links.
- **Wipe a noisy run** — delete the Run row; cascade removes its tests.
- **Cleanup** — purge old projects/suites entirely.

## Risks of the current setup

- No auth → anyone on the network can wipe everything.
- No audit log.
- Editing `name` without updating `slug` (or vice versa) creates dangling URLs.
- Nothing prevents creating a Suite without a Project, etc., via the admin UI; the schema doesn't enforce all FKs (some are nil-able).

## Rebuild approach: Django Admin + single shared `is_staff` login

**Decided** ([decisions.md](decisions.md) #6): use `django.contrib.admin` mounted at `/admin/`, gated by a single shared `is_staff` user. The public API stays no-auth.

### `core/admin.py`

Five `ModelAdmin` classes plus a small mixin that surfaces the rename-severs-baselines warning ([decisions.md](decisions.md) #4) on the `Project` and `Suite` change-form pages.

```python
# core/admin.py
from django.contrib import admin
from django.utils.html import format_html

from core.models import Baseline, Project, Run, Suite, Test


class RenameWarningMixin:
    """Shows a banner on the change form when editing the `name` of a Project or Suite.

    decisions.md #4: renaming re-slugs the model, which changes every contained
    Test's `key` on next ingest and severs the link to existing Baselines.
    The banner makes that visible before save instead of being a silent
    "what just happened to my data" moment.
    """
    change_form_template = 'admin/core/rename_warning_change_form.html'

    def render_change_form(self, request, context, *args, **kwargs):
        obj = context.get('original')
        # Only show the banner on edit, not on add (no existing baselines to sever).
        context['show_rename_warning'] = obj is not None
        return super().render_change_form(request, context, *args, **kwargs)


@admin.register(Project)
class ProjectAdmin(RenameWarningMixin, admin.ModelAdmin):
    list_display    = ('name', 'slug', 'suite_count', 'created_at')
    search_fields   = ('name', 'slug')
    readonly_fields = ('slug', 'created_at', 'updated_at')   # slug is auto-derived from name

    def suite_count(self, obj):
        return obj.suites.count()
    suite_count.short_description = 'Suites'


@admin.register(Suite)
class SuiteAdmin(RenameWarningMixin, admin.ModelAdmin):
    list_display    = ('name', 'project', 'slug', 'next_run_seq', 'created_at')
    list_filter     = ('project',)
    search_fields   = ('name', 'slug')
    readonly_fields = ('slug', 'next_run_seq', 'created_at', 'updated_at')


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display    = ('sequential_id', 'suite', 'project_name', 'test_count', 'created_at')
    list_filter     = ('suite__project', 'suite')
    search_fields   = ('suite__name', 'suite__project__name')
    readonly_fields = ('sequential_id', 'created_at', 'updated_at')
    ordering        = ('-id',)

    def project_name(self, obj):
        return obj.suite.project.name
    project_name.short_description = 'Project'

    def test_count(self, obj):
        return obj.tests.count()
    test_count.short_description = 'Tests'


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display    = ('name', 'browser', 'size', 'passed', 'diff_pct', 'run_label', 'created_at')
    list_filter     = ('passed', 'browser', 'run__suite__project')
    search_fields   = ('name', 'key', 'run__suite__name', 'run__suite__project__name')
    readonly_fields = (   # computed by the diff pipeline; never hand-edit
        'key', 'diff', 'passed',
        'screenshot', 'screenshot_baseline', 'screenshot_diff',
        'screenshot_thumb', 'screenshot_baseline_thumb', 'screenshot_diff_thumb',
        'created_at', 'updated_at',
    )
    fieldsets = (
        (None, {
            'fields': ('run', 'name', 'browser', 'size', 'source_url'),
        }),
        ('Diff parameters', {
            'fields': ('fuzz_level', 'highlight_colour', 'crop_area'),
            'description': (
                'Editing these does NOT re-run the diff. To rebaseline, use the '
                '"Set as baseline" button on the run page or delete the Baseline row.'
            ),
        }),
        ('Result (read-only)', {
            'fields': ('passed', 'diff', 'key'),
        }),
        ('Files (read-only)', {
            'classes': ('collapse',),
            'fields': (
                'screenshot', 'screenshot_baseline', 'screenshot_diff',
                'screenshot_thumb', 'screenshot_baseline_thumb', 'screenshot_diff_thumb',
            ),
        }),
    )

    def diff_pct(self, obj):
        return f"{obj.diff:.2f}%" if obj.diff else "0%"
    diff_pct.short_description = 'Diff'

    def run_label(self, obj):
        return f"{obj.run.suite.project.name} / {obj.run.suite.name} #{obj.run.sequential_id}"
    run_label.short_description = 'Run'


@admin.register(Baseline)
class BaselineAdmin(admin.ModelAdmin):
    list_display    = ('name', 'browser', 'size', 'suite', 'has_screenshot', 'created_at')
    list_filter     = ('suite__project', 'suite')
    search_fields   = ('name', 'key')
    readonly_fields = ('key', 'screenshot', 'thumbnail', 'test', 'created_at', 'updated_at')

    def has_screenshot(self, obj):
        return bool(obj.screenshot)
    has_screenshot.boolean = True
    has_screenshot.short_description = 'File present'
```

A few choices worth flagging:

- **`slug`, `next_run_seq`, `key`, `diff`, `passed`, and every `FileField` are `readonly_fields`** — these are all computed, either by `Model.save()` overrides or by the diff pipeline. Letting a human edit them produces inconsistent state with no benefit.
- **`Test`'s fieldsets group the editable diff parameters together** with a description that makes clear: editing them does *not* re-run the diff. This is the most common admin foot-gun ("I bumped fuzz_level, why is the test still failing?") — call it out at the form level, don't make the operator infer it.
- **`has_screenshot` boolean column on `BaselineAdmin`** — surfaces orphan-UID rows where the FK is intact but the S3 object is gone. Same drift the comparison service logs about; making it visible in the admin lets an operator spot it without grepping logs.

`passed` is on the model (not `pass`) because `pass` is a Python keyword. The DRF serializer maps `passed` back to `"pass"` on the wire for CI client compatibility — see [data-model.md](data-model.md) and [api.md](api.md).

### Rename-warning template

The mixin above points at `admin/core/rename_warning_change_form.html`. Place it under `core/templates/admin/core/`:

```html
{# core/templates/admin/core/rename_warning_change_form.html #}
{% extends "admin/change_form.html" %}
{% load i18n %}

{% block field_sets %}
  {% if show_rename_warning %}
    <div class="messagelist" style="margin: 0 0 1em 0;">
      <p class="warning" style="background:#fff8e1; border-left:4px solid #f0b400; padding:1em;">
        <strong>Renaming severs baselines.</strong>
        Changing <code>name</code> auto-updates the slug. Every <em>future</em> Test
        ingested into this {{ opts.verbose_name }} will compute a new
        <code>key</code>, leaving any existing Baseline orphaned.
        Consider deleting stale Baselines before renaming, or accept that the
        next run for that key will have nothing to compare against and will
        auto-establish as the new baseline (you'll see the "new baseline"
        badge on the run page).
      </p>
    </div>
  {% endif %}
  {{ block.super }}
{% endblock %}
```

The template extends Django's stock `admin/change_form.html` and only overrides `field_sets` to inject the banner above the form fields. Everything else — actions, breadcrumbs, the save bar — stays untouched.

For the template loader to find this file, add `core/templates/` to `TEMPLATES[0]['DIRS']` in `settings.py`, **or** rely on the app-template discovery that Django enables by default when `'APP_DIRS': True` is set (it is, in the Django-startproject default). The `admin/core/` path under `core/templates/` is what the loader expects.

### Why a mixin, not duplicated `change_form_template` declarations

Two ModelAdmin classes (Project and Suite) need the same banner; future renames could affect Tests too if we ever surface a name field there (we don't today). The mixin lets the banner travel with one line of inheritance instead of three copies of `change_form_template = '...'` plus three `render_change_form` overrides. If a future ModelAdmin needs the warning, it inherits the mixin and the banner appears.

### Authentication setup

- Standard Django session login at `/admin/login/` (the form Django ships with). Username + password, cookie-based session. **No SSO, no OAuth, no basic auth** — keep it dead simple.
- One `is_staff = True`, `is_superuser = True` user, created at deploy time via the `ensure_admin_user` management command (below). Reads `ADMIN_USERNAME` / `ADMIN_PASSWORD` from the env (see [deployment-and-config.md](deployment-and-config.md)).
- Credentials stored in the secret manager (not the repo, not the env file checked in).
- Document rotation: when the password needs to change, update the env, redeploy, and `ensure_admin_user` reconciles the new password into the existing row.

#### `core/management/commands/ensure_admin_user.py`

Idempotent reconcile-style command. Runs on every container start (called from `scripts/start.sh` — see [deployment-and-config.md](deployment-and-config.md)). On first run it creates the admin user; on subsequent runs it updates the password if and only if the env var has changed. No-op when `ADMIN_PASSWORD` is unset.

```python
# core/management/commands/ensure_admin_user.py
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure a single is_staff/is_superuser admin exists, matching ADMIN_USERNAME/ADMIN_PASSWORD."

    def handle(self, *args, **options):
        username = settings.ADMIN_USERNAME
        password = settings.ADMIN_PASSWORD

        if not password:
            # Don't create a passwordless admin. Loud no-op so an operator notices
            # if ADMIN_PASSWORD is missing in production.
            self.stdout.write(self.style.WARNING(
                "ADMIN_PASSWORD is unset; skipping admin bootstrap."
            ))
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'is_staff': True, 'is_superuser': True, 'email': ''},
        )

        # Always reconcile flags — protects against an operator editing the row
        # by hand and accidentally clearing is_staff.
        user.is_staff = True
        user.is_superuser = True

        # Only rehash if the password actually changed; check_password is
        # constant-time and avoids invalidating sessions on every deploy.
        if not user.check_password(password):
            user.set_password(password)
            self.stdout.write(self.style.SUCCESS(
                f"Admin {'created' if created else 'updated'}: {username}"
            ))
        elif created:
            user.set_password(password)
            self.stdout.write(self.style.SUCCESS(f"Admin created: {username}"))
        else:
            self.stdout.write(f"Admin already up-to-date: {username}")

        user.save()
```

#### Why reconcile, not just create

A simple "create if missing" command leaves you stuck the moment someone needs to rotate the password — you'd have to either run `manage.py changepassword` interactively (defeats the point of env-driven config) or delete the row and let the next deploy recreate it (loses any session, audit, or admin-log data tied to the user). The reconcile pattern means rotating the password is just a redeploy with a new `ADMIN_PASSWORD` value.

The two guard rails worth keeping:

- **`if not password: return`** — the command is idempotent, but creating an admin with a blank password would be a foot-gun. Loud no-op instead.
- **`if not user.check_password(password)`** — skip `set_password()` when the hash already matches. Prevents every deploy from rehashing and re-saving, which would also bump `last_login`-adjacent timestamps in some auth backends.

#### Operational notes

- The command runs **every** container start (in `start.sh` between `migrate` and `collectstatic`). That's deliberate: it costs ~50ms and means rolling deploys can't end up with mismatched admin state across pods.
- If you need to disable the admin entirely in a particular environment, leave `ADMIN_PASSWORD` unset and the command no-ops. The Django Admin URLs still resolve, but there's no usable login.
- `manage.py changepassword <username>` still works for one-off password changes outside the env-driven flow. Use it sparingly — the next deploy will overwrite the change with whatever's in `ADMIN_PASSWORD`.

`spectre/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core',
]

# Login required only for /admin/. The DRF views opt out.
LOGIN_URL = '/admin/login/'
```

### What the admin must support (parity with the Django admin)

- List / search / filter Projects, Suites, Runs, Tests, Baselines.
- Create / edit / delete each.
- Bulk delete (Django Admin has this built-in via the actions dropdown).
- Cascade delete (Project → Suites → Runs → Tests; Suite → Baselines) — handled by `on_delete=CASCADE` on the model FKs, not the admin.
- Export to CSV/JSON if needed → add `django-import-export`. Defer until asked.

### Not an admin feature

"Set as baseline" lives on the public run page (no auth) — see [ui.md](ui.md) and [api.md](api.md).

### Risks specific to this setup

- **Single shared credential** — no audit trail of which person made a change. Mitigate by limiting who has the password and rotating after offboarding.
- **Renaming a project/suite re-slugs and re-keys** — see [decisions.md](decisions.md) #4. The admin form should display a banner on the edit page warning that changing `name` will sever existing baselines. Implement with a custom `change_form_template` or a `formfield_for_dbfield` override.
