# AWS IAM Authentication — Infra Prerequisites

This app can authenticate to S3, RDS, and ElastiCache (Valkey) using IAM roles
instead of static credentials, enabled via `AWS_IAM_AUTH_ENABLED=1`. This is
an application-code feature only — the AWS-side identities and grants below
must be provisioned out-of-band (no Terraform/CloudFormation exists in this
repo) before enabling the flag in an environment.

## S3

- Grant the pod's IRSA role `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`
  on the target bucket (`AWS_STORAGE_BUCKET_NAME`).
- No other setup — boto3's default credential chain picks up the IRSA
  identity automatically via the `AWS_ROLE_ARN` / `AWS_WEB_IDENTITY_TOKEN_FILE`
  env vars EKS injects into the pod.

## RDS

1. Create the Postgres user and grant it the `rds_iam` role:
   ```sql
   CREATE USER iam_app_user WITH LOGIN;
   GRANT rds_iam TO iam_app_user;
   ```
2. Grant the pod's IRSA role `rds-db:connect` on the DB user's resource ARN:
   `arn:aws:rds-db:<region>:<account-id>:dbuser:<resource-id>/iam_app_user`.
3. Set `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` (no
   password — the app generates a fresh 15-minute auth token per connection).

## ElastiCache (Valkey)

1. Create an ElastiCache "user" with IAM auth mode enabled and associate it
   with the target replication group.
2. Grant the pod's IRSA role `elasticache:Connect` on that user/cache-cluster
   ARN.
3. Set `REDIS_HOST`, `REDIS_PORT`, `REDIS_IAM_USERNAME`.

## Error behavior

There is no fallback to static credentials if IAM auth fails (missing IRSA
env vars, expired role, network error, etc.) — failures propagate as normal
connection errors, exactly as a bad static password would today.
