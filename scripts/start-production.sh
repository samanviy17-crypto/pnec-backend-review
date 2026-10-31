#!/bin/sh
# Manual startup only. No schema changes, seeding, deployment or remote access.
set -eu
: "${SECRET_KEY:?Set a strong independently generated signing secret}"
: "${FRONTEND_URL:?Set the approved HTTPS frontend origin}"
: "${DATABASE_URL:?Set an explicit persistent database URL}"
: "${SECURITY_STATE_PATH:?Set an absolute persistent security-state path}"
: "${UPLOAD_FOLDER:?Set an absolute persistent upload path}"
export FLASK_ENV=production
exec gunicorn --bind "${BIND_ADDRESS:-127.0.0.1}:${PORT:-8425}" --workers "${WEB_CONCURRENCY:-2}" --timeout 60 --access-logfile - --error-logfile - 'app:create_app()'
