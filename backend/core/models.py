from django.db import models, transaction
from django.utils.text import slugify

# Each FileField needs a top-level callable, not a closure — Django serializes
# `upload_to` references into migrations and can't import nested functions.
#
# All test_* helpers require instance.id to be set (i.e. the Test row must
# already be saved). Never pass a file when calling Test.objects.create() —
# save first, then assign the file field separately, or you get paths like
# screenshots/None/original.png.


def test_screenshot_path(instance, _original_name):
    return f"screenshots/{instance.id}/original.png"


def test_baseline_path(instance, _original_name):
    return f"screenshots/{instance.id}/baseline.png"


def test_diff_path(instance, _original_name):
    return f"screenshots/{instance.id}/diff.png"


def test_screenshot_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300.jpg"


def test_baseline_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300-baseline.jpg"


def test_diff_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300-diff.jpg"


def baseline_screenshot_path(instance, _original_name):
    return f"baselines/{instance.key}/screenshot.png"


def baseline_thumbnail_path(instance, _original_name):
    return f"baselines/{instance.key}/thumb-300.jpg"


class Project(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Suite(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="suites")
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    next_run_seq = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "slug"], name="unique_suite_slug_per_project"),
        ]

    def __str__(self):
        return f"{self.project.name} / {self.name}"

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Run(models.Model):
    suite = models.ForeignKey(Suite, on_delete=models.CASCADE, related_name="runs")
    sequential_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["suite", "sequential_id"], name="unique_run_seq_per_suite"),
        ]

    def __str__(self):
        return f"{self.suite} run #{self.sequential_id}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            with transaction.atomic():
                suite = Suite.objects.select_for_update().get(pk=self.suite_id)
                self.sequential_id = suite.next_run_seq
                suite.next_run_seq += 1
                suite.save(update_fields=["next_run_seq"])
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class Test(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="tests")
    name = models.CharField(max_length=255)
    browser = models.CharField(max_length=255)
    size = models.CharField(max_length=255)
    source_url = models.URLField(max_length=2048, blank=True, default="")

    fuzz_level = models.CharField(max_length=10, default="30%")
    highlight_colour = models.CharField(max_length=6, default="ff0000")
    crop_area = models.CharField(max_length=64, blank=True, default="")

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    is_new_baseline = models.BooleanField(
        null=True,
        default=None,
        help_text=(
            "None = processing not yet complete; True = this submission "
            "established a new baseline; False = baseline already existed."
        ),
    )

    diff = models.FloatField(default=0)
    passed = models.BooleanField(default=False)
    key = models.CharField(max_length=512, db_index=True, blank=True)

    screenshot = models.FileField(
        upload_to=test_screenshot_path,
        null=True,
        blank=True,
    )
    screenshot_baseline = models.FileField(
        upload_to=test_baseline_path,
        null=True,
        blank=True,
    )
    screenshot_diff = models.FileField(
        upload_to=test_diff_path,
        null=True,
        blank=True,
    )
    screenshot_thumb = models.FileField(
        upload_to=test_screenshot_thumb_path,
        null=True,
        blank=True,
    )
    screenshot_baseline_thumb = models.FileField(
        upload_to=test_baseline_thumb_path,
        null=True,
        blank=True,
    )
    screenshot_diff_thumb = models.FileField(
        upload_to=test_diff_thumb_path,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.browser}, {self.size})"

    def save(self, *args, **kwargs):
        self.key = self._compute_key()
        super().save(*args, **kwargs)

    def _compute_key(self) -> str:
        suite = self.run.suite
        return slugify(f"{suite.project.name} {suite.name} {self.name} {self.browser} {self.size}")[:512]


class Baseline(models.Model):
    suite = models.ForeignKey(Suite, on_delete=models.CASCADE, related_name="baselines")
    test = models.ForeignKey(
        Test,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Test that produced this baseline; informational only.",
    )
    name = models.CharField(max_length=255)
    browser = models.CharField(max_length=255)
    size = models.CharField(max_length=255)
    key = models.CharField(max_length=512, unique=True, db_index=True)

    screenshot = models.FileField(
        upload_to=baseline_screenshot_path,
        null=True,
        blank=True,
    )
    thumbnail = models.FileField(
        upload_to=baseline_thumbnail_path,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.key
