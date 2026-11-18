# PNEC Docker preparation — Draft PR review, 2026-11-17

**Server deployment requires separate approval.** Both Compose definitions passed configuration validation with synthetic inputs. Image build and container runtime validation require a Docker-enabled machine. Review these files in backend Draft PR #1.

## Guide comparison and source audit

Read directly: [OCS deployment](https://pages.opencodingsociety.com/flask/deploy?context=topics), [OCS Flask anatomy](https://pages.opencodingsociety.com/flask/anatomy). The sequence below follows the guide. Modern `docker compose` replaces its legacy `docker-compose` spelling. The guide does not prescribe a particular Python base image, full Compose schema, or PNEC environment variable set.

| Requirement | PNEC preparation |
|---|---|
| Dockerfile | Previously absent. Python 3.12 slim, pinned existing requirements, explicit source copies, non-root UID 10001, Gunicorn, readiness healthcheck. Actual base-image/platform compatibility and digest remain unverified until build. |
| Compose / overrides | Previously absent. New production file requires explicit project/image/env/data/host-port values. Separate standalone local file; never merge it with production. No production override was found. |
| Port | Container EXPOSE, Gunicorn, healthcheck and config use 8475. Host port requires explicit assignment; no default production host port. Native development default remains 8425. |
| Startup | `gunicorn --bind 0.0.0.0:8475 --workers 2 main:app`; entrypoint refuses unsafe policy, missing writable state, or unready schema. Never runs production migrations/seeding automatically. |
| Environment | Preserve existing strong secret, exact FRONTEND_URL, credentialed CORS, CSRF, secure cookies, file rate limits, explicit persistent database and disabled auto-initialization. Existing `production.env.example` supplies variable names, not credentials. |
| Local verification | Standalone tmpfs database, random synthetic secret, no production env file, providers disabled, explicit disposable bootstrap. Run the foreground container checks before server use. |
| Repository | Existing feature branch and Draft PR #1 for code review. |
| Cockpit | Inspect containers/ports/project ownership first. Dedicated project recommended; actual server directory/project/image/container identity unknown. |
| nginx | Loopback host mapping and hostname-specific proxy. Flask owns CORS; do not copy the guide's wildcard CORS/OPTIONS shortcut, which conflicts with credentialed authentication. |
| HTTPS | Only after HTTP proxy and DNS verification: scoped Certbot command below, then browser cookie/CSRF checks over real HTTPS. |

`.dockerignore` allows only required source; no `.env`, databases, instance data, keys, logs or credentials enter the context. requirements.txt is unchanged. `main.py` remains the entry point; its development server is not used in Docker. `scripts/start-review.sh` is ephemeral review-only and must never start production. Migration 0002 is additive; the existing readiness endpoint checks its revision and announcement table. New production startup checks are read-only. Existing systemd instructions are an alternative deployment manager, not a second service to run alongside Compose.

## 1. Inventory and reserve a port before server use

User-provided Cockpit observations: BEASTS `beasts_backend-web-1`, image `beasts_flask`, project `beasts_backend` uses 8425; Pirates uses 8426. No listener was observed at 8475, but **8475 is NOT reserved**. These observations were not independently checked. No PNEC assignment or reservation registry was found in this repository. Nothing establishes BEASTS ownership by PNEC: leave it untouched.

Adya must verify the server's assignment registry and inspect, read-only:

```sh
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
docker compose ls
sudo ss -ltnp
```

Confirm reserved PNEC host port, unique project/image names, persistent data ownership and deployment directory with the server owner. An unused socket alone is insufficient. Recommend a **new dedicated PNEC project**, unless an existing service is positively identified as PNEC and its update separately authorized. `pnec-api` below is the proposed Compose service key, not a confirmed server container. Do not reuse BEASTS project/image names. Never run global Docker cleanup, stop existing containers, or expose Docker inspect environment output.

## 2. Local foreground Docker prerequisite — NOT RUN

On a Docker-enabled machine with Compose V2, use this worktree and an unused local port. Local port availability is independent of server reservation. The local file is standalone; do not supply both Compose files. Preserve these non-secret exported values in both terminals:

```sh
cd ~/PNEC-Workspace/pnec-production-backend-20261117
export PNEC_LOCAL_PROJECT="pnec_local_$(date +%s)"
export PNEC_LOCAL_TAG="validation-$(git rev-parse --short HEAD)"
export PNEC_LOCAL_PORT=8475
# Inspect local listeners and docker ps first; choose another LOCAL port if needed.
docker compose -f docker-compose.local.yml config --quiet
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up
```

Keep `up` in the foreground (no `-d`). In another terminal, export the exact same three values, then:

```sh
curl --fail "http://127.0.0.1:$PNEC_LOCAL_PORT/api/health"
curl --fail "http://127.0.0.1:$PNEC_LOCAL_PORT/api/ready"
docker compose -f docker-compose.local.yml exec -T pnec-api python scripts/check-docker-local.py
```

Run the existing production-policy tests inside the image using an allowlisted source copy (no private environment or data). These commands are also unrun:

```sh
export PNEC_TEST_SOURCE="$(mktemp -d /tmp/pnec-docker-source.XXXXXX)"
python3 - <<'PYCODE'
import os, shutil
from pathlib import Path
source = Path(os.environ['PNEC_TEST_SOURCE'])
for name in ('app', 'migrations', 'tests'):
    shutil.copytree(name, source / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env*', '*.db', '*.sqlite*'))
PYCODE
docker compose -f docker-compose.local.yml run --rm --no-deps \
  -e FLASK_ENV=development -e PYTHONPATH=/validation \
  -v "$PNEC_TEST_SOURCE:/validation:ro" -w /validation --entrypoint python pnec-api \
  -m pytest -q -p no:cacheprovider tests/test_production_preparation.py
```

The HTTP probe generates only synthetic registration data, tests session/cookie flags, CSRF, resident denial, CORS and logout. It deliberately sends secure cookies explicitly over loopback for API checks; this does **not** certify browser HTTPS behavior. Database migrations occur only in tmpfs via the explicitly marked local bootstrap. A worker restart fails safely rather than reusing/resetting that database; recreate this disposable project to restart testing.

After inspection confirms the project is the unique disposable one created above: Ctrl-C in its foreground terminal, then `docker compose -f docker-compose.local.yml down`. No `down -v`, prune, unrelated container removal, or production mounts. Compare Docker inventory before/after to ensure unrelated applications are unchanged.

## 3. Review and deployment approval

Record the foreground Docker checks in Draft PR #1. Obtain explicit server deployment and migration approval separately.

## 4. Server clone/build and loopback verification — future authorized work only

Unknown values must be supplied by Adya after verification, not guessed:

- `PNEC_DEPLOY_DIR`: approved dedicated checkout path; clone this repository there only after publication/approval, or verify existing checkout ownership and cleanliness.
- `PNEC_APPROVED_SHA`: reviewed, published exact commit.
- `PNEC_COMPOSE_PROJECT`: assigned unique PNEC project.
- `PNEC_IMAGE`: dedicated PNEC image with reviewed version tag (never `beasts_flask`).
- `PNEC_HOST_PORT`: formally reserved host port; candidate 8475.
- `PNEC_ENV_FILE`: absolute private production environment file, outside checkout/build context.
- `PNEC_DATA_DIR`: existing, verified persistent directory owned/writable by container UID/GID 10001; do not chown someone else's data. Bind creation is disabled.

Private environment must retain existing approved credentials, FLASK_ENV=production, FRONTEND_URL=https://powaynec.opencodingsociety.com, a strong SECRET_KEY, explicit DATABASE_URL, SECURITY_STATE_PATH and UPLOAD_FOLDER. For SQLite use a path inside `/var/lib/pnec` (the persistent mount), e.g. an approved `db/pnec.db` under it; precreate its parent plus upload/security directories with private permissions. MySQL requires independently verified connectivity, driver/server compatibility, backups and restored-clone migration rehearsal. Do not generate/rotate production secrets as part of deployment. No seeded production users.

Commands below are a handoff, **not executed**. Missing variables intentionally stop progress:

```sh
cd "${PNEC_DEPLOY_DIR:?Server owner must verify directory}"
test "$(git rev-parse HEAD)" = "${PNEC_APPROVED_SHA:?Exact reviewed commit required}"
git status --short
# Stop if dirty or the wrong repository/project; verify origin privately.
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml build
# Equivalent dedicated image build: docker build --tag "$PNEC_IMAGE" .
# BACKUP + RESTORED-CLONE REHEARSAL + EXPLICIT MIGRATION APPROVAL required first:
docker compose -f docker-compose.yml run --rm --no-deps --entrypoint python pnec-api \
  -m flask --app main:app db current
docker compose -f docker-compose.yml run --rm --no-deps --entrypoint python pnec-api \
  -m flask --app main:app db upgrade
docker compose -f docker-compose.yml run --rm --no-deps --entrypoint python pnec-api \
  -m flask --app main:app db current
# Require 0002_announcements and independently verify retained records.
docker compose -f docker-compose.yml up -d --build pnec-api
docker compose -f docker-compose.yml ps
curl --fail "http://127.0.0.1:$PNEC_HOST_PORT/api/health"
curl --fail "http://127.0.0.1:$PNEC_HOST_PORT/api/ready"
```

Confirm PNEC response identity/revision, not merely HTTP 200; wrong content suggests collision. Startup never repairs a stale database. Capture image ID/digest, approved SHA, project and actual container name after creation. Do not operate on any other Compose project.

## 5. DNS verification, nginx, then Certbot

Only after correct server loopback responses: verify the API hostname's existing DNS resolves to the intended server `3.129.109.200`; preserve correct records. No DNS changes are authorized. Do not copy the guide's example classroom hostname/record.

Use `deploy/pnec-api.docker-http.nginx.conf.example` as the **initial HTTP-only** dedicated virtual host. Replace `@RESERVED_HOST_PORT@` with the confirmed port; verify existing virtual hosts first. Actual nginx include path/site enablement requires server verification. Flask remains the sole CORS authority; forward cookies, Origin, Authorization and CSRF normally, with no wildcard CORS or generic OPTIONS interception.

After explicitly authorized nginx configuration: `sudo nginx -t`, then an approved nginx reload (shared-host adaptation of the guide's restart). Verify HTTP hostname routing before:

```sh
sudo certbot --nginx -d powaynec-api.opencodingsociety.com
sudo nginx -t
curl --fail https://powaynec-api.opencodingsociety.com/api/health
curl --fail https://powaynec-api.opencodingsociety.com/api/ready
```

Only this hostname; no other certificates, shared network configuration or accounts. Existing TLS nginx template is for the post-certificate state, not initial setup. Validate certificate chain/expiry without `-k`; then real HTTPS browser login/logout, Secure/HttpOnly/SameSite cookies, allowed-origin credentialed requests, PATCH/PUT/DELETE and X-CSRF-Token, rejected foreign origins, resident/admin separation. Confirm frontend compatibility before release.

## 6. Updates, backup and rollback

Before any migration: identify actual database and uploads, take consistent backups with writes quiesced as needed, verify checksums/permissions and restore into a **new disposable target**; rehearse additive migration and retained-data checks there. SQLite snapshot utility refuses an existing destination. MySQL backup/restore must be independently verified by its owner. Record previous image digest, SHA, environment reference, nginx config and database revision; keep private values out of logs.

Updates use this dedicated project's approved image only, after the same checks. Rollback application image only if compatible with current schema. The original baseline application expects revision 0001 and will fail readiness against 0002: do not blindly revert it. Restore a verified backup to a new approved target only under explicit rollback approval, accounting for post-backup writes/uploads; never downgrade/drop/overwrite production data automatically. Never use `start-review.sh`, seed scripts, `down -v`, shared-project restarts or global cleanup.

## Evidence and remaining gates

See [DOCKER-VALIDATION.md](DOCKER-VALIDATION.md) for native tests and Compose configuration results. Before server deployment, complete the Docker build and runtime checks, nginx validation, TLS/browser testing and database rehearsal. Confirm the server directory, project/image/container identity, persistent storage, existing service ownership and formal port reservation.
