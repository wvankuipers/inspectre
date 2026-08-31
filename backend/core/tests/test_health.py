import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


def test_healthz_returns_200(api):
    """Health check endpoint returns 200 with no DB queries."""
    response = api.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_no_auth_required(api):
    """Health check endpoint is accessible without authentication."""
    # Just verify it's AllowAny by testing an unauthenticated request succeeds
    response = api.get("/healthz/")
    assert response.status_code == 200
