from unittest.mock import patch

from core.services.s3 import get_s3_client


class TestGetS3ClientStaticCredentials:
    def test_passes_static_credentials_when_iam_auth_disabled(self, settings):
        settings.AWS_IAM_AUTH_ENABLED = False
        settings.AWS_ACCESS_KEY_ID = "test-key"
        settings.AWS_SECRET_ACCESS_KEY = "test-secret"
        settings.AWS_S3_REGION_NAME = "us-east-1"
        settings.AWS_S3_ENDPOINT_URL = None

        with patch("core.services.s3.boto3.client") as mock_client:
            get_s3_client()

        _, kwargs = mock_client.call_args
        assert kwargs["aws_access_key_id"] == "test-key"
        assert kwargs["aws_secret_access_key"] == "test-secret"


class TestGetS3ClientIamAuth:
    def test_omits_static_credentials_when_iam_auth_enabled(self, settings):
        settings.AWS_IAM_AUTH_ENABLED = True
        settings.AWS_S3_REGION_NAME = "us-east-1"
        settings.AWS_S3_ENDPOINT_URL = None

        with patch("core.services.s3.boto3.client") as mock_client:
            get_s3_client()

        _, kwargs = mock_client.call_args
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs
