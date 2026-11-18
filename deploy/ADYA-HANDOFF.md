> Docker/Cockpit preparation: follow [OCS-DOCKER-HANDOFF.md](OCS-DOCKER-HANDOFF.md) in guide order. Docker validation is pending. The native systemd procedure below is an alternative; do not run two deployment managers for the same PNEC service.

# Adya/server administrator handoff — prepared only, no production action performed

Target host: **3.129.109.200**. Frontend origin:
**https://powaynec.opencodingsociety.com**. API:
**https://powaynec-api.opencodingsociety.com**.

The latest read-only audit found correct DNS targets, but a mismatched API TLS
certificate and an unrelated nginx application at the backend hostname. Health,
readiness and required PNEC routes returned 404. Do not reuse that application's
unit/upstream/certificate or change its configuration without identifying it.
No authenticated server/Cockpit access was available to Codex. Actual service,
checkout, virtualenv, database and certificate paths are **not verified**. Every
`<...>`/`@...@` below is an administrator-confirmed value, not a discovered path.

## 1. Identify the existing service — READ ONLY first

In Cockpit inspect Services, Logs, networking/listeners and the server's approved
application inventory. Determine whether PNEC already has a systemd unit/container,
which account owns it, its working directory, ExecStart, environment-file path,
upstream port, restart policy and deployed commit. Do not print secret values.
Equivalent read-only commands (use the confirmed unit/path):

```sh
systemctl status <PNEC_SERVICE> --no-pager
systemctl show <PNEC_SERVICE> -p User -p Group -p WorkingDirectory -p ExecStart -p EnvironmentFiles
ss -ltnp
git -C <DEPLOY_DIRECTORY> rev-parse HEAD
```

Review logs locally; redact personal data/tokens before sharing. Do not copy
`systemctl show -p Environment`, `/proc/*/environ`, a real env file or database
records into GitHub. Confirm the checkout is the approved PNEC backend, not a
classroom starter. Record the exact frontend/backend release SHA pair.
If there is no PNEC service, the proposed unit template is a starting point only;
choose an unused loopback upstream and dedicated account after approval.

## 2. Inventory nginx and TLS — no edits until approved

Inspect the effective nginx configuration locally and identify the port 80/443
virtual hosts, server_name, certificate SAN/path and proxy_pass handling this API.
The API hostname needs its own server block pointing to PNEC Gunicorn on loopback.
Preserve unrelated projects, default vhosts and certificates.

`pnec-api.nginx.conf.example` preserves `/api/...` paths and delegates CORS to
Flask. Remove only conflicting CORS/blanket-OPTIONS directives in the PNEC vhost
once their source is confirmed; do not disable CSRF or authorize broad origins.
Gunicorn must not be publicly exposed. Forwarded headers alone do not establish
a trusted proxy boundary: current auth limits conservatively use the peer address.
Validate rate-limit behavior behind the real proxy; do not blindly add ProxyFix,
trust arbitrary X-Forwarded-For, or disable limits to solve a shared-peer bucket.

After approval, provision a certificate whose SAN includes exactly the API
hostname using the server's established ACME process. Confirm HTTP challenge
routing/webroot (or approved DNS challenge), renewal timer and renewal reload.
Do not overwrite another project's certificate. GitHub manages the FRONTEND
certificate separately after the chosen production Pages publisher is bound.

## 3. Environment and persistence

Use `production.env.example` as a list of required names, not a replacement for
an existing private env file. Preserve approved secrets/credentials; the operator
supplies missing values privately. Required policy:

- FLASK_ENV=production; exact FRONTEND_URL above; no ephemeral review mode.
- Existing strong SECRET_KEY; Secure/HttpOnly host-only cookies, SameSite=Lax
  for the two HTTPS production subdomains. No broad cookie domain is needed.
- Exact CORS/CSRF frontend origin; credentials enabled; GET/HEAD/POST/PUT/PATCH/
  DELETE/OPTIONS and Authorization/Content-Type/X-CSRF-Token preflights.
- Explicit persistent SQLite absolute path OR supported MySQL configuration,
  never both configuration forms and never an accidental development fallback.
- Absolute persistent uploads/security-state paths writable only as required by
  the service account. Back up security-state/config securely, not publicly.
- Rate limiting and authorization remain enabled. App workers do not create or
  seed production schema. Do not set ADMIN_PASSWORD merely to restart a service.
- Verify existing mail/provider settings privately where those features are in
  release scope. Example mail is disabled; real reset delivery is NOT certified.

Never use `scripts/start-review.sh` or the frontend's local-review launcher for
production: they deliberately use temporary synthetic databases.

## 4. Rehearse database changes on a sanitized clone first

The reviewed baseline 0001 is unchanged. New head is **0002_announcements**.
The application factory now registers the existing announcement blueprint.
Migration0002 creates the absent table or validates an exactly compatible existing
one and adopts it without changing any row, ID or foreign key. Column/type/length/
nullability, primary/foreign keys, uniqueness and orphan checks stop on drift.
No destructive downgrade, drop, deletion, blind stamp or automatic repair exists.

Record DB engine/version and current Alembic revision using administrator-local
read-only inspection. Rehearse both the exact live-schema adoption path and a
restore to a NEW target; SQLite tests and MySQL DDL compilation do not establish
MySQL execution compatibility. Do not blindly stamp 0001/0002 to bypass a failure.
MySQL DDL can commit partially: stop on any error and review before retrying.
Do not change the frozen 0001 migration to accommodate unknown server drift.

## 5. Backups and rollback gate — BEFORE any authorized release

Coordinate a write-quiescent/consistent snapshot of database, uploads and necessary
private configuration; record checksums, timestamp/recovery point and permissions.
For SQLite, the reviewed `scripts/sqlite_snapshot.py` makes a verified copy to a
NEW path and refuses overwrite. For MySQL, the administrator uses the existing
approved consistent backup procedure; do not invent a generic dump without checking
the actual engine/storage/transaction setup. Rehearse restoration on a separate
target and verify uploads/foreign keys as well as database integrity.

Retain the prior secure code/artifact and a tested rollback plan. The old backend
expects revision 0001, so simply restarting that image against 0002 can fail its
readiness gate. Use a separately verified rollback-compatible code version that
understands the additive schema, or an explicitly approved coordinated restore
to a NEW target. A restore can lose writes after the recovery point; obtain an
operator-approved recovery/reconciliation decision. Never run destructive downgrade
or restore over the resident database as an automatic rollback.

## 6. Authorized release commands — NOT executed by Codex

Only after owner approval, backup/restore rehearsal and exact service/path/SHA
confirmation. Use the existing operator deployment process to install the reviewed
backend release; do not `git pull` over teammate work or invent the service path.
Run migration once, not independently in each Gunicorn worker:

```sh
cd <DEPLOY_DIRECTORY>
<VENV_DIRECTORY>/bin/python -m flask --app main:app db current
<VENV_DIRECTORY>/bin/python -m flask --app main:app db upgrade
<VENV_DIRECTORY>/bin/python -m flask --app main:app db current
```

The second current must report 0002_announcements. A startup does not require
`release-seed`; do not seed/reset administrators or reference data automatically.
Any needed seed is a separate approved, audited operation.

After config/certificate changes are reviewed, run `nginx -t` before an approved
nginx reload. In Cockpit restart ONLY the identified PNEC service; equivalent:

```sh
sudo systemctl restart <PNEC_SERVICE>
sudo systemctl status <PNEC_SERVICE> --no-pager
```

Whether nginx needs reload depends on actual changed files. Do not restart the
whole host or unrelated services. Observe service logs and rollback gates.

## 7. Independent acceptance — normal TLS, no insecure flag

```sh
curl --fail --show-error https://powaynec-api.opencodingsociety.com/api/health
curl --fail --show-error https://powaynec-api.opencodingsociety.com/api/ready
curl --fail --show-error -i -X OPTIONS \
  -H 'Origin: https://powaynec.opencodingsociety.com' \
  -H 'Access-Control-Request-Method: PATCH' \
  -H 'Access-Control-Request-Headers: Authorization,Content-Type,X-CSRF-Token' \
  https://powaynec-api.opencodingsociety.com/api/auth/profile
```

Require certificate hostname validation, health ok/not-review, readiness 200 and
schema 0002, one exact Access-Control-Allow-Origin plus credentials=true, and
PATCH/header support. Confirm those public results match the pinned service SHA
and actual process/upstream; an environment label alone is not provenance.
An unknown route must not get a fake successful nginx preflight.

Authenticated registration/login/logout, resident privacy/role denial, Profile,
household/quiz/check-in/hazard persistence, volunteer capacity/claims and admin
notification publishing need explicitly approved synthetic end-to-end acceptance,
not real resident tests. Check mail/reset only if authorized/in scope. Production
frontend cutover waits for these gates and separate publication approval.

## GitHub work versus administrator work

Codex can prepare local branches/config/tests and a separate publisher workflow
for review. Push/PR changes/merges/deployment need the owner's next authorization.
Adya/admin owns actual server identity, vhost/upstream, certificate, private env,
DB engine/adoption/backup/restore, service restart and operational evidence.
Correct existing DNS is not an application deployment. No DNS change is required
by the prepared source changes; stop if the administrator finds contradictory facts.
