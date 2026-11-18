#!/bin/sh
# No schema creation, migration, seeding or credential mutation in production startup.
set -eu
test "${FLASK_PORT:-8630}" = 8630 || { echo 'Container listener must remain 8630; align Dockerfile/Compose/Gunicorn before changing it.' >&2; exit 1; }
if [ "${1:-}" = gunicorn ]; then
  case "$*" in
    *scripts.docker_local_app:app*)
      test "${PNEC_DOCKER_DISPOSABLE_TEST:-}" = true || { echo 'Disposable bootstrap requires the explicit local-only marker.' >&2; exit 1; } ;;
    *) python scripts/check-container-readiness.py ;;
  esac
fi
# Explicit one-off Flask migration commands remain operator-controlled, never automatic.
exec "$@"
