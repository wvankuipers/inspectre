import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


def test_healthz_returns_200(api, django_assert_num_queries):
    """Health check endpoint returns 200 with no DB queries."""
    with django_assert_num_queries(0):
        response = api.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
