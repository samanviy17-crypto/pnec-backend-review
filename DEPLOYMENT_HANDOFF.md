# PNEC deployment handoff — operator review required

Prepared October 30, 2026. **Production NO-GO until the operator gates below are
satisfied. These are manual future instructions, not authorization to deploy.**
No production connections, credentials, DNS changes or deployments were used to
prepare this package. No GitHub workflow or automatic deployment is included.
Changes are local and uncommitted; approval and publication must happen first.

## Sources and domains

Frontend: https://github.com/samanviy17-crypto/pnec-frontend-review
Backend: https://github.com/samanviy17-crypto/pnec-backend-review
Use the exact subsequently approved commit IDs, never a moving main branch.
The published initial commits predate this readiness work.

Previously documented domains are `https://pnec.opencodingsociety.com` (frontend,
root path) and `https://beasts.opencodingsociety.com` (API). These were read from
existing local CNAME/runbook documentation; their live ownership, DNS, TLS and
running revisions were **not** inspected. No CNAME is activated by this package.
`powaynec.com` is an informational external link, not a runtime theme dependency.

## Required operator gates (B)

1. Confirm target OS/Python/Ruby versions, actual database engine/version and
   sanitized production schema. Supply schema-only metadata without residents,
   password hashes, tokens or uploads. Rehearse both migrations on that schema.
   SQLite fixtures and MySQL DDL compilation do not certify the live MySQL schema.
2. Confirm current immutable backend/frontend artifacts, running revision, trusted
   proxy boundary, persistent volume paths/permissions and an approved maintenance
   window. Confirm these private review repos remain isolated from deployment apps.
3. Produce a coordinated, access-restricted database + uploads backup and prove
   restoration to a NEW isolated target. Confirm the previous secure application
   artifact can run against the additive schema, or rehearse full recovery.
4. Supply new independent SECRET_KEY, explicit persistent DATABASE_URL, protected
   upload/limiter paths, initial admin credentials only if needed, SMTP credentials
   and at least one server-side chat provider key. Never reuse exposed teaching keys.
5. Confirm SMTP delivery/reset URL and provider quotas/restrictions from an approved
   staging environment. Local tests mock external providers. Weather/geocoding/news,
   browser speech and optional IP geolocation need operator acceptance; they fail
   safely when unavailable. Confirm privacy disclosures, approved public FAQ/coordinator contact content, event
   dates, organization claims and public contact details; sanitized placeholders are
   not a production directory.
6. Resolve historical exposures: Google owners must confirm status/remediation of
   fingerprints `03d2d733653d`, `301a4c85bc96`, `630104b38c93`, `6f88776992d3`,
   `a1bb64931449`, `b91a0c81fa28`, `d529ae9387fb`. No leaked values were tested.
   Owners of ADMIN_PASSWORD, DEFAULT_PASSWORD and MIRAGE_PASSWORD must confirm
   non-use or rotate affected/reused credentials and invalidate sessions as needed.
   Repository/data owner must review the historical identity backup/uploads,
   consent/retention and incident response. Clean repos do not remediate old history.
7. Confirm a public contact email and donation destination. The snapshot's public
   `contact@example.test` is sanitized, not deliverable. Set the public build contact
   value before launch. Online donation buttons stay disabled without an approved
   HTTPS payment URL; no fake PayPal merchant ID is used.

## Hosting requirements

Static HTTPS hosting serves only the frontend build artifact, preserving directory
indexes (including `/role-quiz/` and `/donation-form/`). No Node service is required.
Ruby/Bundler and Python are build tools; Gemfile.lock includes Linux platforms.
Backend needs Unix/Linux, Python 3.12+ (local execution used 3.14), Gunicorn, and a
persistent SQLite filesystem or MySQL/PyMySQL. Ruby 3.3+ is recommended; local build
used Ruby 4.0.6. Linux execution has not been performed in this workspace.
Use one application host with multiple workers sharing a LOCAL limiter state path;
file locks are not a multi-host/NFS limiter. Do not horizontally scale without a
reviewed distributed auth limiter. Place persistent uploads outside the code tree.
Start with 2 workers; capacity/quotas need operator load acceptance.

## Environment checklist (no values in Git)

Backend required: `FLASK_ENV=production`, strong `SECRET_KEY` (32+ random characters),
`FRONTEND_URL` (exact HTTPS root origin), `DATABASE_URL` (absolute persistent SQLite
URL or `mysql+pymysql` with URL-encoded credentials), absolute `UPLOAD_FOLDER` and
`SECURITY_STATE_PATH`. `ALLOWED_FRONTEND_ORIGINS` is an operator-approved allowlist;
it must include FRONTEND_URL. Production CORS/CSRF permits only that selected origin.
Do not set wildcard origins. Use same-site HTTPS frontend/API domains for cookies.

SMTP: `MAIL_DELIVERY=smtp`, `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`/`MAIL_USE_SSL`
(select one), `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`. Reset links use
FRONTEND_URL. Configure an approved sender and verify delivery before launch.
Public directory fallback: `PUBLIC_CONTACT_EMAIL` (owner-approved public email; no
private coordinator directory is copied). Initial seed only: `ADMIN_EMAIL`, `ADMIN_PASSWORD` (12+ strong characters), optional
`ADMIN_DISPLAY_NAME`; an existing admin is never overwritten by the seed command.
Chat: `GROQ_API_KEY` (primary) and/or `GEMINI_API_KEY` (fallback); optional model
variables and `GEMINI_RATE_LIMIT_PER_MINUTE`. New keys remain backend-only. Image understanding requires GEMINI_API_KEY; it never silently uses the text-only
Groq path. Actual provider image behavior needs operator staging acceptance.
Optional `REDIS_URL` for provider limits. Optional VAPID configuration is deferred;
the browser push feature is not enabled by this release.
`BEARER_TOKEN_MAX_AGE` defaults 86400 seconds. `PORT=8425`, `BIND_ADDRESS=127.0.0.1`,
`WEB_CONCURRENCY=2`. Hosted containers may use BIND_ADDRESS=0.0.0.0 only behind an
approved private ingress. Do not expose Gunicorn directly to the public Internet.
Keep `GITHUB_PUBLISH_ENABLED=false`, and GITHUB_TOKEN/OWNER/REPO unset. Running or
deploying PNEC needs no GitHub write credential. The optional editor Git publishing
path requires separate review and refuses main/master destinations.

Frontend build: public `PNEC_FRONTEND_ORIGIN`, `PNEC_API_ORIGIN`, `PNEC_CONTACT_EMAIL`,
optional `PNEC_DONATION_URL`. No frontend API keys or passwords. The safe default
build uses reserved `.invalid` API hosts; the production script requires real
operator-provided origins. Do not deploy the default review build.

## Exact future sequence

Run only after separate deployment authorization, against approved paths. Commands
below use environment variables that the operator supplies through a protected
secret mechanism; do not type secrets into shell history or share environment dumps.
Define BACKEND_ROOT, FRONTEND_ROOT, APPROVED_DB_PATH, BACKUP_DB_PATH, RESTORED_DB_PATH
and BUILD_OUTPUT as approved absolute paths. BACKUP_DB_PATH, RESTORED_DB_PATH and
BUILD_OUTPUT must be NEW and outside source. The SQLite script refuses overwrites.

1. Approve/publish these exact changes. Checkout immutable approved review commits
   into new release directories. Keep old artifacts available. Install dependencies:

   ```sh
   cd "$BACKEND_ROOT"
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/pip check
   cd "$FRONTEND_ROOT"
   bundle install
   bundle check
   ```

2. In approved staging, execute the isolated local rehearsal first:

   ```sh
   cd "$BACKEND_ROOT"
   .venv/bin/python -B scripts/rehearse-deployment.py
   .venv/bin/python -B -m pytest -q -p no:cacheprovider
   ```

3. Maintenance/backup: operator quiesces all API writers and background jobs, records
   the current artifact/revision and takes a coordinated protected upload snapshot.
   For SQLite only, with the source path verified by the operator:

   ```sh
   .venv/bin/python -B scripts/sqlite_snapshot.py --approved --source "$APPROVED_DB_PATH" --destination "$BACKUP_DB_PATH"
   .venv/bin/python -B scripts/sqlite_snapshot.py --approved --source "$BACKUP_DB_PATH" --destination "$RESTORED_DB_PATH"
   ```

   Retain the generated manifests privately. Verify restored table counts/integrity
   and application behavior against the NEW restore target. Never point rehearsal at
   production. MySQL requires operator-approved logical/physical backup tooling and
   an actual isolated restore rehearsal; do not use the SQLite commands for MySQL.

4. With the protected staging/target environment selected and backup accepted:

   ```sh
   cd "$BACKEND_ROOT"
   .venv/bin/python -B -m flask --app main:app db current
   .venv/bin/python -B -m flask --app main:app db upgrade
   .venv/bin/python -B -m flask --app main:app db current
   .venv/bin/python -B -m flask --app main:app release-seed --approved
   ```

   Expected head: `0002_pnec_features` (0001 frozen baseline plus additive
   announcements/chat tables). Existing reference data/accounts are preserved.
   Fresh neighborhood seeds use the same 60 number/name/zone entries as the approved
   frontend map. Existing neighborhood rows/assignments are not overwritten; an
   operator must review old-number mappings before migration of resident assignments.
   Image-space polygons are not GPS boundaries; without validated geographic
   polygons, address/GPS lookup offers manual neighborhood selection rather than
   guessing. Unknown columns/types/constraints cause migration refusal. Never blindly stamp,
   call db.create_all on production or edit migration history. The root package can
   cause duplicate factory imports with `--app app:create_app()`; use `main:app` for
   Flask CLI as rehearsed. Worker import uses `app:create_app()` normally.

5. Start the backend under the operator's existing service manager (manual script;
   it does not migrate, seed or install a service):

   ```sh
   cd "$BACKEND_ROOT"
   PATH="$BACKEND_ROOT/.venv/bin:$PATH" sh scripts/start-production.sh
   ```

   From a second operator shell, verify locally before admitting traffic:

   ```sh
   .venv/bin/python -B scripts/deployment-smoke.py --base-url http://127.0.0.1:8425
   ```

6. Build the frontend with public origin/contact variables supplied:

   ```sh
   cd "$FRONTEND_ROOT"
   python3 -B scripts/build-production.py --destination "$BUILD_OUTPUT"
   ```

   The script refuses an existing output/source destination. Inspect the artifact;
   no tests, source scripts, docs, .env or workflows should be hosted. Publish ONLY
   this artifact through the operator's approved manual hosting procedure, after API
   acceptance. No host-specific publish command is invented: the live hosting
   provider, paths and service mechanism are not available locally.

7. Operator validates TLS at both documented domains, correct static directory
   indexing, cache invalidation, exact CORS preflight and no mixed content. Preserve
   the root frontend path. Proxy must strip untrusted forwarded headers. Application
   currently ignores forwarded client-IP headers, conservatively aggregating limits
   at the proxy IP; confirm acceptable rates or authorize a trusted-proxy design
   before launch. Do not blindly add ProxyFix or trust arbitrary forwarded headers.

8. Post-deployment acceptance: health/ready 200, schema head, synthetic registration,
   login/profile/logout, password reset email and one-time reuse refusal, admin deny
   for resident, checklist/quiz persistence, volunteer capacity/cancel, check-in
   privacy, supply pledges, hazard moderation, FAQ votes/questions, gallery uploads,
   mobile/tablet/desktop navigation and external-provider degraded states. Use
   synthetic operator-owned accounts only and an approved cleanup/retention plan.

## Rollback and failure recovery

Stop on any migration/startup/smoke failure; keep traffic on the previous healthy
artifact. A failed SQLite migration may leave additive DDL: never assume transaction
rollback undoes schema changes. Destructive Alembic downgrade is intentionally
refused. Preserve failed-state evidence privately. If the previous secure artifact
has been rehearsed against the additive schema, revert application/static artifact
only. Otherwise restore the coordinated backup to NEW database/upload paths,
validate integrity/counts, then let the operator explicitly switch protected target
configuration and traffic. Never overwrite or delete the failed/current database.
Reconcile writes after the recovery point before a data rollback; obtain approval
for any possible loss. Retain backups according to the owner's private retention
policy. These scripts never change DNS, restart production or promote traffic.

## Deferred functionality (C)

Git-backed theme publishing remains disabled; in-database CMS editing remains
available. Optional RPG is explicitly deferred; core quiz/checklist remain. Live WordPress
newsletter signup is replaced by a contact link pending an approved mailing-list
integration. Donation payments are disabled until the owner confirms a destination.
Chat streaming is disabled unless an explicitly supported endpoint is configured;
one-shot chat remains. Analytics distinguishes server-persisted counts from local
browser history; local chats are not silently uploaded and feedback/topic collection
is not implemented server-side. Complete theme pixel equivalence, browser speech
provider availability, push integration and distributed scaling are not certified.

## Evidence and time estimate

See VALIDATION_REPORT.md and the external readiness-evidence directory. Local
synthetic migration/recovery and startup passing does not establish production GO.
After all operator inputs are available and staging succeeds, allow roughly 1–2
hours for a controlled deployment and acceptance; schema drift, provider access,
backup size or incident remediation may take longer. No live deployment time can
be guaranteed without those inputs.

References: [Jekyll configuration](https://jekyllrb.com/docs/configuration/options/),
[Flask/Gunicorn](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/),
[SQLite DDL transaction limitations](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
