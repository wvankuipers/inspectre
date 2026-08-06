"""ElastiCache IAM auth token generation for redis-py's CredentialProvider interface.

ElastiCache IAM auth tokens are short-lived presigned request URLs (not real
HTTP requests) generated via botocore's request signer for the
"elasticache:connect" action, following the same mechanism AWS documents for
IAM authentication to ElastiCache for Valkey/Redis.
"""

import boto3
from botocore.model import ServiceId
from botocore.signers import RequestSigner
from django.conf import settings
from redis.credentials import CredentialProvider


class IAMElastiCacheCredentialProvider(CredentialProvider):
    def __init__(self):
        self._user_id = settings.REDIS_IAM_USERNAME
        # The signed host is the cache name, not the connection endpoint in
        # REDIS_HOST. AWS lowercases cache names at creation time, so a token
        # signed with mixed case is rejected.
        self._cache_name = settings.REDIS_IAM_CACHE_NAME.lower()
        self._region = settings.AWS_REGION

    def get_credentials(self) -> tuple[str, str]:
        session = boto3.session.Session()
        request_signer = RequestSigner(
            ServiceId("elasticache"),
            self._region,
            "elasticache",
            "v4",
            session.get_credentials(),
            session.events,
        )
        token = request_signer.generate_presigned_url(
            {
                "method": "GET",
                "url": f"https://{self._cache_name}/",
                "body": {"Action": "connect", "User": self._user_id},
                "headers": {},
                "context": {},
            },
            operation_name="connect",
            expires_in=900,
            region_name=self._region,
        ).removeprefix("https://")
        return self._user_id, token
