"""ElastiCache IAM auth token generation for redis-py's CredentialProvider interface.

ElastiCache IAM auth tokens are short-lived presigned request URLs (not real
HTTP requests) generated via botocore's request signer for the
"elasticache:connect" action, following the same mechanism AWS documents for
IAM authentication to ElastiCache for Valkey/Redis.
"""

import boto3
from botocore.model import ServiceId
from botocore.signers import RequestSigner
from redis.credentials import CredentialProvider


class IAMElastiCacheCredentialProvider(CredentialProvider):
    def __init__(self, user_id: str, replication_group_id: str, region: str):
        self._user_id = user_id
        self._replication_group_id = replication_group_id
        self._region = region

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
                "url": f"https://{self._replication_group_id}/",
                "body": {"Action": "connect", "User": self._user_id},
                "headers": {},
                "context": {},
            },
            operation_name="connect",
            expires_in=900,
            region_name=self._region,
        ).removeprefix("https://")
        return self._user_id, token
