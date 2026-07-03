import mimetypes
from pathlib import Path

import factory
import pytest

from core.models import Baseline, Project, Run, Suite, Test

FIXTURES = Path(__file__).parent / "fixtures" / "images"


# ---- Image fixtures --------------------------------------------------------
# Files land in slice 4 with the comparison service; declared now so future
# packs don't need to retrofit. Tests that need them will fail loudly when
# missing, which is the right signal.


@pytest.fixture
def testcard():
    return FIXTURES / "testcard.jpg"


@pytest.fixture
def testcard_large():
    return FIXTURES / "testcard_large.jpg"


@pytest.fixture
def run1():
    return FIXTURES / "run1.png"


@pytest.fixture
def run2():
    return FIXTURES / "run2.png"


@pytest.fixture
def upload(tmp_path):
    """Wrap a Path as a Django UploadedFile-like object."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    def _upload(path: Path) -> SimpleUploadedFile:
        mime, _ = mimetypes.guess_type(path.name)
        return SimpleUploadedFile(path.name, path.read_bytes(), content_type=mime or "application/octet-stream")

    return _upload


# ---- Model factories -------------------------------------------------------


class ProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Project

    name = factory.Sequence(lambda n: f"Project {n}")


class SuiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Suite

    project = factory.SubFactory(ProjectFactory)
    name = factory.Sequence(lambda n: f"Suite {n}")


class RunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Run

    suite = factory.SubFactory(SuiteFactory)


class TestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Test

    run = factory.SubFactory(RunFactory)
    name = factory.Sequence(lambda n: f"test_{n}")
    browser = "Chrome"
    size = "1024"


@pytest.fixture
def project_factory():
    return ProjectFactory


@pytest.fixture
def suite_factory():
    return SuiteFactory


@pytest.fixture
def run_factory():
    return RunFactory


@pytest.fixture
def test_factory():
    return TestFactory


@pytest.fixture
def baseline_factory(suite_factory):
    """Baseline doesn't fit factory_boy as cleanly (no defaults that produce a unique key);
    a function fixture lets the test specify what it needs.
    """
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = {
            "suite": kwargs.get("suite") or suite_factory(),
            "name": kwargs.pop("name", "Homepage"),
            "browser": kwargs.pop("browser", "Chrome"),
            "size": kwargs.pop("size", "1024"),
            "key": kwargs.pop("key", f"baseline-{counter['n']}"),
        }
        defaults.update({k: v for k, v in kwargs.items() if k not in defaults})
        return Baseline.objects.create(**defaults)

    return _make


# ---- Hermetic storage ------------------------------------------------------


@pytest.fixture(autouse=True)
def _filesystem_storage(settings, tmp_path):
    """Swap S3 for FileSystemStorage so unit tests stay hermetic. Integration
    tests that need real S3 semantics use moto explicitly.
    """
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "storage")},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
