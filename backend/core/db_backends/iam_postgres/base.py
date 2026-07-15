"""Postgres DB backend that authenticates to RDS via IAM auth tokens.

Generates a fresh 15-minute IAM auth token on every new physical connection
(CONN_MAX_AGE is 0 by default, so this naturally satisfies token expiry
without a background refresh mechanism).
"""

import boto3
from django.conf import settings
from django.db.backends.postgresql.base import DatabaseWrapper as PostgresDatabaseWrapper


class DatabaseWrapper(PostgresDatabaseWrapper):
    def get_connection_params(self):
        params = super().get_connection_params()

        if not settings.AWS_IAM_AUTH_ENABLED:
            return params

        rds_client = boto3.client("rds", region_name=settings.AWS_REGION)
        params["password"] = rds_client.generate_db_auth_token(
            DBHostname=params["host"],
            Port=int(params["port"]),
            DBUsername=params["user"],
            Region=settings.AWS_REGION,
        )
        params["sslmode"] = "require"
        return params
