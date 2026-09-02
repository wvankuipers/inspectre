import pytest
from django.conf import settings


@pytest.mark.django_db
def test_is_secure_reflects_forwarded_proto_header(client):
    response = client.get("/api/projects/", HTTP_X_FORWARDED_PROTO="https")
    assert response.wsgi_request.is_secure() is True


@pytest.mark.django_db
def test_is_secure_false_without_forwarded_proto_header(client):
    response = client.get("/api/projects/")
    assert response.wsgi_request.is_secure() is False


def test_csrf_trusted_origins_defaults_to_empty():
    assert settings.CSRF_TRUSTED_ORIGINS == []


def test_celery_task_acks_late_default():
    """Verify CELERY_TASK_ACKS_LATE defaults to True (reliability fix from prior task)."""
    assert settings.CELERY_TASK_ACKS_LATE is True


def test_celery_worker_prefetch_multiplier_default():
    """Verify CELERY_WORKER_PREFETCH_MULTIPLIER defaults to 1 (reliability fix from prior task)."""
    assert settings.CELERY_WORKER_PREFETCH_MULTIPLIER == 1
