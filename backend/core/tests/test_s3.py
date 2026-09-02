from unittest.mock import patch

from core.services.s3 import generate_presigned_url, get_presign_s3_client, staging_key_for_test


class TestStagingKeyForTest:
    def test_returns_correct_key_for_test_id(self):
        assert staging_key_for_test(42) == "screenshots/staging/42/upload.png"

    def test_returns_correct_key_for_different_test_id(self):
        assert staging_key_for_test(1) == "screenshots/staging/1/upload.png"


class TestGeneratePresignedUrl:
    def test_returns_none_for_empty_key(self):
        assert generate_presigned_url("") is None

    def test_returns_none_for_none_key(self):
        assert generate_presigned_url(None) is None

    def test_calls_boto3_generate_presigned_url_with_bucket_and_key(self, settings):
        settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        with patch("core.services.s3.get_presign_s3_client") as mock_get_client:
            mock_client = mock_get_client.return_value
            mock_client.generate_presigned_url.return_value = "https://signed.example/foo"

            result = generate_presigned_url("screenshots/1/original.png")

        assert result == "https://signed.example/foo"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "screenshots/1/original.png"},
            ExpiresIn=86400,
        )

    def test_respects_custom_expires_in(self, settings):
        settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        with patch("core.services.s3.get_presign_s3_client") as mock_get_client:
            mock_client = mock_get_client.return_value
            mock_client.generate_presigned_url.return_value = "https://signed.example/foo"

            generate_presigned_url("some/key.png", expires_in=900)

        _, kwargs = mock_client.generate_presigned_url.call_args
        assert kwargs["ExpiresIn"] == 900

    def test_generate_presigned_url_produces_sigv4_url(self, settings):
        """No boto3 mocking here: sign a real (dummy-credentialed) request and
        inspect the resulting query string. This would have caught botocore
        defaulting to SigV2 presigning in regions like eu-west-1.
        """
        get_presign_s3_client.cache_clear()
        settings.AWS_IAM_AUTH_ENABLED = False
        settings.AWS_ACCESS_KEY_ID = "dummy-key"
        settings.AWS_SECRET_ACCESS_KEY = "dummy-secret"
        settings.AWS_S3_REGION_NAME = "eu-west-1"
        settings.AWS_S3_PRESIGN_ENDPOINT_URL = None
        settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        url = generate_presigned_url("some/key.png")
        get_presign_s3_client.cache_clear()

        assert "X-Amz-Signature" in url
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
