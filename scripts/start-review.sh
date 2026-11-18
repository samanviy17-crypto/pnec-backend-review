#!/bin/sh
# Render Free review only: fresh disposable state, never an existing database.
set -eu
test "${PNEC_REVIEW_EPHEMERAL:-}" = "true" || {
  echo 'Set PNEC_REVIEW_EPHEMERAL=true only for the separate synthetic review service.' >&2
  exit 1
}
test "${FRONTEND_URL:-}" = "https://samanviy17-crypto.github.io/pnec-frontend-review" || exit 1
test -z "${DATABASE_URL:-}${DB_ENDPOINT:-}${DB_USERNAME:-}${DB_PASSWORD:-}" || {
  echo 'Review service refuses supplied database connections.' >&2
  exit 1
}
test -z "${GITHUB_TOKEN:-}${GITHUB_OWNER:-}${GITHUB_REPO:-}" || exit 1
review_state=$(mktemp -d /tmp/pnec-review-XXXXXX)
export FLASK_ENV=production
export FLASK_PORT="${PORT:-10000}"
export DATABASE_URL="sqlite:///$review_state/review.db"
export SECURITY_STATE_PATH="$review_state/security-limits.json"
export UPLOAD_FOLDER="$review_state/uploads"
export MAIL_DELIVERY=disabled
mkdir -p "$UPLOAD_FOLDER"
python -m flask --app main:app db upgrade
python -m flask --app main:app release-seed --approved
exec gunicorn --bind "0.0.0.0:$FLASK_PORT" --workers 1 --timeout 120 main:app
