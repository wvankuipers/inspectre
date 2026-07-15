from unittest.mock import MagicMock, patch

from core.cache_backends.iam_credential_provider import IAMElastiCacheCredentialProvider


class TestGetCredentials:
    def test_returns_username_and_generated_token(self, settings):
        settings.REDIS_IAM_USERNAME = "iam-cache-user"
        settings.REDIS_HOST = "inspectre-valkey"
        settings.AWS_REGION = "eu-west-1"
        provider = IAMElastiCacheCredentialProvider()

        mock_session = MagicMock()
        mock_signer = MagicMock()
        mock_signer.generate_presigned_url.return_value = (
            "https://inspectre-valkey/?Action=connect&User=iam-cache-user&X-Amz-Signature=abc"
        )
        mock_session.get_credentials.return_value = MagicMock()

        with (
            patch(
                "core.cache_backends.iam_credential_provider.boto3.session.Session",
                return_value=mock_session,
            ),
            patch("core.cache_backends.iam_credential_provider.RequestSigner") as mock_signer_cls,
        ):
            mock_signer_cls.return_value = mock_signer
            username, token = provider.get_credentials()

        assert username == "iam-cache-user"
        assert token == "inspectre-valkey/?Action=connect&User=iam-cache-user&X-Amz-Signature=abc"
        mock_signer.generate_presigned_url.assert_called_once()
        call_kwargs = mock_signer.generate_presigned_url.call_args
        request_dict = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["request_dict"]
        assert request_dict["body"] == {"Action": "connect", "User": "iam-cache-user"}
        assert request_dict["url"] == "https://inspectre-valkey/"
        assert request_dict["headers"] == {}
