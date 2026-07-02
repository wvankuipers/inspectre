#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py ensure_admin_user

exec gunicorn inspectre.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
