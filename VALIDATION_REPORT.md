# PNEC deployment-readiness validation — October 30, 2026

**Local readiness package: prepared for exact-change review. Production: NO-GO.**
No commits, pushes, PRs, merges, production access or deployment were performed.
All readiness changes are uncommitted in the new isolated review working copies.
The original published review commits and original repositories remain unchanged.

## Executed checks

| Check | Actual result |
|---|---|
| Backend pytest, Python 3.14 | 215 passed; 8,853 deprecation warnings; see final log |
| Every registered API method/path, anonymous bounded input | 149 checked; no unhandled 500, privileged actions denied; HTML login redirects validated |
| Frontend offline Node unit suites | 4 passed (includes nested renderer, store, tool and CMS assertions) |
| Built JavaScript syntax | 284 asset/inline checks passed |
| Existing frontend regression scripts | All 10 passed |
| Full-site audit | All 39 built HTML pages, 117 viewport cases (390/768/1440), 2,080 local references; no JS exceptions, horizontal overflow, broken local targets or live WordPress assets |
| Homepage responsive regression | All 12 widths 320–1440 passed, including retained negative-margin assertion and video bounds |
| Production Jekyll build | Executed successfully with pinned Bundler stack; 127 static files; build-time public API/contact configuration |
| Build exposure audit | No environment examples, tests, scripts, dependencies or handoff documents in static artifact |
| Database rehearsals | Empty initialization, exact-model schema, known legacy nullable profile adoption, existing-row preservation, repeated migrations/seed, schema-drift rejection, refused destructive downgrade, backup/restore and injected partial-migration recovery passed |
| WSGI startup | Actual manual startup script, 2 Gunicorn workers on loopback; migrated/seeded synthetic SQLite, health/ready 200, login/profile/admin analytics/logout passed |
| Python dependencies | Fresh requirements installation, pip check passed; pip-audit reported no known vulnerabilities |
| Ruby dependencies | Bundler resolution/check and production build passed; OSV scan of 34 package/version pairs reported no known vulnerabilities |
| npm dependencies | None declared; Node-only offline tests passed |
| Source gates | Full current frontend/backend file trees checked for credential signatures, identity-record JSON, .env/private/runtime files, symlinks and deployment workflows; no findings |
| Git isolation | Both remote repos still private, Actions disabled, no workflows/secrets/environments/hooks/deployments; remote main unchanged |

Browser tests use synthetic accounts, loopback/disposable state or locally fulfilled
reserved `.invalid` URLs. External providers are blocked/mocked. The 39-page audit
also scrolls content and checks reveal fallback on the nine captured sample views.
Automated bounds checks plus sample screenshot inspection are not pixel-equivalence
certification or a complete assistive-technology audit. All earlier failed runs
remain in the external evidence folder; the final named logs supersede them.

## Functionality and fixes

- Self-contained PNEC CSS replaces remote WordPress/Jupiter/Raven assets and Google
  fonts. Original layout markup, page assets, local SCSS and core navigation remain.
  Fixed desktop video bleed within reserved padding, replaced legacy headers with
  one shared local header, removed duplicate footer navigation and invalid logo
  paths, broken RPG quiz target and duplicate API_BASE declaration on admin page.
- Fresh neighborhood seeds match the approved 60-row map number/name/zone data,
  while existing rows/assignments are preserved. Only public metadata is included.
- Build-time public origin/contact configuration reaches layouts and standalone
  pages. Default review origins remain inert. Production builds require explicit
  HTTPS origins and approved public contact email; no source edits are required.
- RPG engine dependencies could not be safely restored. Owner-authorized deferral
  disables its launch link and replaces the broken wrapper with a clear notice.
  Original code remains in the initial review commit/snapshot. Core quiz works.
- Removed the unrelated classroom backend landing page; root now exposes only
  PNEC service discovery. Registered previously missing announcement/chat blueprints. Added protected admin
  FAQ list/delete, gallery metadata delete and aggregate analytics routes. Added a
  separate frozen additive 0002 migration rather than editing migration 0001.
- Main dashboard waits for shared helpers and verifies the real server identity
  before opening; session-only credentials work and forged cached roles do not.
  Blog controls recognize session-only credentials.
- Fixed auth form lockout bypass and open redirect risk by reusing secured API login
  and restricting redirect targets. GET admin logout is now confirmation-only;
  POST delegates to protected account logout. Resident admin-page access denies.
- Uploads enforce extension/signature, exclusive random storage, authorization,
  field bounds and referenced event validity. Existing public upload delivery uses
  attachment/nosniff. Metadata removal retains files for operator recovery policy.
- Production uses exact configured frontend CORS/CSRF origin, persistent database
  selection and protected upload/limiter paths. Readiness checks revision + tables.
- Editor GitHub publishing is off by default and has no legacy owner/repo/main
  fallback. Running/deploying requires no GitHub write credential.
- Chat defaults to supported one-shot backend API; image field names match backend.
  Image understanding requires approved Gemini config; no silent text-only fallback.
  Provider errors are sanitized and no browser service-key mode is shipped.

## Remaining issues, explicitly classified

### A — Must fix before deployment

No currently known locally reproducible application test/build failure remains.
Deployment must remain NO-GO until the B prerequisites are satisfied. Any schema,
provider, proxy or target-environment failure discovered in staging becomes A and
requires correction/revalidation; do not treat this report as production approval.

### B — Requires owner or production-operator access/information

- Approved geographic boundaries and public directory content are unavailable;
  automatic exact GPS/address-to-neighborhood assignment is not certified. Fresh
  seeds now match the frontend map, but existing-number mappings require operator
  reconciliation without overwriting resident assignments.
- Actual database engine/version and schema-only sanitized production fixture were
  unavailable. SQLite fixtures and MySQL DDL compilation passed; an actual MySQL
  migration/restore rehearsal was not executed. No production database was read.
- Target Linux/container environment, current secure rollback artifacts, maintenance
  process, actual coordinated database/upload backup and restore/traffic switch
  need operator rehearsal. Only macOS Python 3.14/Ruby 4.0 execution was available.
- SMTP, provider access/quotas, image provider, weather/news/geocoding, actual TLS,
  domains, same-site cookies and reverse-proxy limits need approved staging checks.
  Behind an unconfigured proxy client-IP limits aggregate at the proxy IP; the
  operator must accept capacity or approve a trusted-proxy configuration.
- Public contact email, FAQ/coordinator contact content, event dates, organization
  claims and optional payment destination need owner confirmation. No private
  directory or historical personal data was copied to fill these gaps.
- Account-wide GitHub App installation scope was not visible through current
  authorization. Previously supplied owner isolation confirmation remains the basis
  for review publication. Administrators must assess later integration-scope changes
  before production enablement; no new publication confirmation is being requested. Repo-level
  Actions/workflow/secret/environment/hook/deployment checks are clear.
- Owners must remediate seven historical Google fingerprints, determine whether the
  three inherited password defaults were ever used/reused, rotate/invalidate affected
  credentials and assess old identity backup/upload exposure. No key was tested,
  rotated or revoked. Old public history/forks/caches remain outside these clean repos.

### C — Optional post-launch improvements / explicit deferrals

- RPG, browser push and a reviewed newsletter integration remain deferred.
- Donation payments stay disabled until the owner supplies a verified HTTPS target.
- Git-backed theme publishing remains disabled; in-database CMS editing remains.
- Chat streaming remains off by default; server topic/feedback collection is not
  implemented. Browser analytics remains local; server metrics cover persisted
  sessions/messages only, without exporting transcripts or identities.
- Full media decoding/antivirus, multi-host rate limits, load acceptance, expanded
  accessibility/pixel-equivalence checks and upstream deprecation cleanup are future
  improvements. Current source guards are pattern/shape scans, not a proof that all
  possible secrets or every security defect are absent.

## Handoff, approval and evidence

[DEPLOYMENT_HANDOFF.md](DEPLOYMENT_HANDOFF.md) is the single deployment sequence,
environment checklist, backup/migration/startup/smoke commands and rollback guide.
Identical copies are included in both repositories for Adya's convenience. Each
manual command was derived from local source; no host-specific publish command,
service name, ingress path or production credential is invented.

Complete exact changed-file lists, full-tree SHA-256 manifests, review patches,
source-preservation checks and all logs are in the local readiness-evidence folder
beside the frontend/backend working copies. No virtual environment, logs, screenshots,
synthetic database or generated build artifact is proposed for Git publication.

Proposed future commits (not created):
- Frontend: `Prepare standalone PNEC frontend and operator deployment handoff`
- Backend: `Complete PNEC API contracts, security and additive deployment migrations`

After exact-change approval, publish to a new `review/deployment-readiness` branch
in each private review repository and request review targeting main. Keep Actions
and Pages disabled/unconfigured. No production change is included in that approval.
Estimated controlled deployment after B gates and staging acceptance: 1–2 hours;
operator access, schema drift or incident remediation may extend that substantially.
