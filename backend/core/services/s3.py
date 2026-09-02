"""Shared S3 client factory."""

from functools import lru_cache

import boto3
from botocore.config import Config
from django.conf import settings


def get_s3_client():
    """Return a boto3 S3 client configured from Django settings.

    Centralises endpoint, credentials, and region so changes only need one edit.
    Always sign requests with SigV4 explicitly: botocore's default signature
    version depends on region metadata (some regions, e.g. eu-west-1, default
    to legacy SigV2), which breaks presigning and is rejected by KMS-encrypted
    buckets outright.
    """
    kwargs = {
        "endpoint_url": settings.AWS_S3_ENDPOINT_URL,
        "region_name": settings.AWS_S3_REGION_NAME,
        "config": Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
    if not settings.AWS_IAM_AUTH_ENABLED:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


@lru_cache(maxsize=1)
def get_presign_s3_client():
    """Return a boto3 S3 client for presigning, using the public-facing endpoint.

    Presigned URLs must be signed against a host the browser can actually reach.
    In dev that's S3_PUBLIC_BASE_URL's origin (localhost:9000), not the
    container-internal AWS_S3_ENDPOINT_URL (minio:9000) used for direct
    upload/download/delete. In prod, both are the same real S3 endpoint.

    Path-style addressing is hardcoded because MinIO in dev is addressed via
    a path prefix (http://localhost:9000/<bucket>/...), not a bucket subdomain;
    real S3 accepts path-style too, so this is a safe universal default.

    Cached with lru_cache: constructing a boto3 client is ~2ms, and this is
    called per-image-field (up to 8 per test row). If AWS_IAM_AUTH_ENABLED,
    the cached client's IAM/IRSA credential provider still refreshes
    credentials internally on its own schedule — caching the client object
    does not cache stale credentials.
    """
    kwargs = {
        "endpoint_url": settings.AWS_S3_PRESIGN_ENDPOINT_URL,
        "region_name": settings.AWS_S3_REGION_NAME,
        "config": Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    }
    if not settings.AWS_IAM_AUTH_ENABLED:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def staging_key_for_test(test_id: int) -> str:
    """Return the S3 key for staging a test's uploaded screenshot.

    Used by the upload flow to stage raw screenshots before async processing.
    """
    return f"screenshots/staging/{test_id}/upload.png"


def generate_presigned_url(key, expires_in=60 * 60 * 24):
    """Return a presigned GET URL for an S3 object key, or None if key is falsy.

    The bucket is private, so every screenshot/baseline/diff/thumbnail URL
    returned by the API must be signed to be browser-reachable.
    """
    if not key:
        return None
    return get_presign_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
