from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.credentials import Credentials

from core.cache_backends.iam_credential_provider import IAMElastiCacheCredentialProvider

# An ElastiCache endpoint and the cache name it belongs to. These are deliberately
# different strings: the connection endpoint is the DNS name, while the IAM token
# must be signed against the cache name. A value that could pass for either would
# not exercise the distinction.
CACHE_NAME = "my-cache"
ENDPOINT = f"master.{CACHE_NAME}.abc123.use1.cache.amazonaws.com"
IAM_USERNAME = "iam-cache-user"
REGION = "us-east-1"


@pytest.fixture
def iam_settings(settings):
    settings.REDIS_HOST = ENDPOINT
    settings.REDIS_IAM_CACHE_NAME = CACHE_NAME
    settings.REDIS_IAM_USERNAME = IAM_USERNAME
    settings.AWS_REGION = REGION
    return settings


@pytest.fixture
def frozen_credentials():
    """Static credentials so the real botocore signer runs deterministically.

    Only get_credentials is stubbed — the session's event emitter is left intact,
    since RequestSigner drives the actual SigV4 signing through it.
    """
    session = boto3.session.Session(region_name=REGION)
    with (
        patch.object(
            session,
            "get_credentials",
            # Any strings work — SigV4 treats these as opaque bytes. Deliberately
            # not AWS's AKIA-prefixed example pair, which trips secret scanners.
            return_value=Credentials(access_key="test-key", secret_key="test-secret"),
        ),
        patch(
            "core.cache_backends.iam_credential_provider.boto3.session.Session",
            return_value=session,
        ),
    ):
        yield


class TestGetCredentials:
    def test_returns_the_iam_username(self, iam_settings, frozen_credentials):
        username, _ = IAMElastiCacheCredentialProvider().get_credentials()

        assert username == IAM_USERNAME

    def test_signs_the_cache_name_not_the_connection_endpoint(self, iam_settings, frozen_credentials):
        """ElastiCache signs the cache name; the host is part of the SigV4 signature.

        Signing the DNS endpoint yields a signature the server cannot reproduce,
        which it reports as "invalid username-password pair or user is disabled"
        (WRONGPASS) — indistinguishable from a genuinely bad password.
        """
        _, token = IAMElastiCacheCredentialProvider().get_credentials()

        assert token.startswith(f"{CACHE_NAME}/?")
        assert ENDPOINT not in token

    def test_token_carries_the_connect_action_and_user(self, iam_settings, frozen_credentials):
        _, token = IAMElastiCacheCredentialProvider().get_credentials()

        query = parse_qs(urlparse(f"https://{token}").query)
        assert query["Action"] == ["connect"]
        assert query["User"] == [IAM_USERNAME]

    def test_token_is_presigned_and_short_lived(self, iam_settings, frozen_credentials):
        _, token = IAMElastiCacheCredentialProvider().get_credentials()

        query = parse_qs(urlparse(f"https://{token}").query)
        assert query["X-Amz-Signature"]
        assert query["X-Amz-Expires"] == ["900"]
        # The scheme is stripped so the token can be sent as an AUTH password.
        assert not token.startswith("https://")

    def test_lowercases_the_cache_name(self, iam_settings, frozen_credentials):
        """AWS lowercases cache names at creation; signing mixed case fails auth."""
        iam_settings.REDIS_IAM_CACHE_NAME = "My-Cache"

        _, token = IAMElastiCacheCredentialProvider().get_credentials()

        assert token.startswith(f"{CACHE_NAME}/?")
