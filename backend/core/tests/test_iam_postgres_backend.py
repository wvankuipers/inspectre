from unittest.mock import MagicMock, patch

import pytest

from core.db_backends.iam_postgres.base import DatabaseWrapper


@pytest.fixture
def wrapper():
    settings_dict = {
        "NAME": "inspectre",
        "USER": "iam_app_user",
        "HOST": "db.example.rds.amazonaws.com",
        "PORT": "5432",
        "PASSWORD": "",
        "OPTIONS": {},
        "TIME_ZONE": None,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
    }
    return DatabaseWrapper(settings_dict, alias="default")


class TestGetConnectionParamsIamAuthEnabled:
    def test_injects_generated_token_as_password_and_forces_sslmode(self, wrapper, settings):
        settings.AWS_IAM_AUTH_ENABLED = True
        settings.AWS_REGION = "eu-west-1"

        mock_rds_client = MagicMock()
        mock_rds_client.generate_db_auth_token.return_value = "generated-iam-token"

        with patch("core.db_backends.iam_postgres.base.boto3.client", return_value=mock_rds_client) as mock_boto:
            params = wrapper.get_connection_params()

        mock_boto.assert_called_once_with("rds", region_name="eu-west-1")
        mock_rds_client.generate_db_auth_token.assert_called_once_with(
            DBHostname="db.example.rds.amazonaws.com",
            Port=5432,
            DBUsername="iam_app_user",
            Region="eu-west-1",
        )
        assert params["password"] == "generated-iam-token"
        assert params["sslmode"] == "require"


class TestGetConnectionParamsIamAuthDisabled:
    def test_uses_configured_password_unchanged(self, wrapper, settings):
        settings.AWS_IAM_AUTH_ENABLED = False
        wrapper.settings_dict["PASSWORD"] = "plain-password"

        with patch("core.db_backends.iam_postgres.base.boto3.client") as mock_boto:
            params = wrapper.get_connection_params()

        mock_boto.assert_not_called()
        assert params["password"] == "plain-password"
        assert "sslmode" not in params or params.get("sslmode") != "require"
