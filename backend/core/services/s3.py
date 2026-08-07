"""Shared S3 client factory."""

import boto3
from botocore.config import Config
from django.conf import settings


def get_s3_client():
    """Return a boto3 S3 client configured from Django settings.

    Centralises endpoint, credentials, and region so changes only need one edit.
    """
    kwargs = {
        "endpoint_url": settings.AWS_S3_ENDPOINT_URL,
        "region_name": settings.AWS_S3_REGION_NAME,
        "config": Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
    if not settings.AWS_IAM_AUTH_ENABLED:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def generate_presigned_url(key, expires_in=60 * 60 * 24):
    """Return a presigned GET URL for an S3 object key, or None if key is falsy.

    The bucket is private, so every screenshot/baseline/diff/thumbnail URL
    returned by the API must be signed to be browser-reachable.
    """
    if not key:
        return None
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
