from unittest.mock import patch

from core.services.s3 import generate_presigned_url


class TestGeneratePresignedUrl:
    def test_returns_none_for_empty_key(self):
        assert generate_presigned_url("") is None

    def test_returns_none_for_none_key(self):
        assert generate_presigned_url(None) is None

    def test_calls_boto3_generate_presigned_url_with_bucket_and_key(self, settings):
        settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        with patch("core.services.s3.get_s3_client") as mock_get_client:
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

        with patch("core.services.s3.get_s3_client") as mock_get_client:
            mock_client = mock_get_client.return_value
            mock_client.generate_presigned_url.return_value = "https://signed.example/foo"

            generate_presigned_url("some/key.png", expires_in=900)

        _, kwargs = mock_client.generate_presigned_url.call_args
        assert kwargs["ExpiresIn"] == 900
