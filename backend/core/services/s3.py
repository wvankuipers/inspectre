"""Shared S3 client factory."""

import boto3
from botocore.config import Config
from django.conf import settings


def get_s3_client():
    """Return a boto3 S3 client configured from Django settings.

    Centralises endpoint, credentials, and region so changes only need one edit.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
