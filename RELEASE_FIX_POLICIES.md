# Seven-blocker correction policies — November 1, 2026

These local fixes are uncommitted and unpublished. They do not authorize a
production change. Use new owner-approved immutable artifacts after review; the
previous review SHAs do not contain these corrections.

## Coordinator assignments: no new database column

`users.neighborhood_id` remains editable residential information only. It is
never a coordinator authorization source. Protected check-ins, hazards, volunteer
rosters and task management use the trusted server configuration
`COORDINATOR_ASSIGNMENTS`, a JSON object mapping account-ID strings to positive
neighborhood IDs, for example `{}` (no assignments). An administrator/operator
must obtain the owner's approved account-ID/neighborhood-ID mapping and apply it
consistently to every worker via protected host configuration. No email/name or
secret is needed in Git. Missing assignments deny coordinator access. Staff and
admin privileges remain role-controlled. Profile JSON cannot edit assignments.
The authenticated account response includes `assigned_neighborhood_id`; the UI
uses this for coordination, and continues using residence for household forms.
No automatic inheritance from editable residence is permitted on role promotion.
Restart workers together after an approved configuration change. This avoids a
production schema migration; a future assignment-management UI/table would need
separate design and migration approval.

## Event/gallery deletion: RESTRICT, never cascade

An event referenced by any gallery entry cannot be deleted (409). Its event row,
all gallery rows and every uploaded file remain intact. The FK enforces this
under races too; the route rolls back and returns a controlled conflict. An
unreferenced event can be deleted. Any future unlink/reassignment is a separate
explicit administrative operation; the release does not automatically clear
relationships or remove files. SQLite connections enable foreign keys before
transactions, including pooled/reopened connections. Existing orphaned data is
not repaired/deleted automatically: an operator must review and correct it in a
separately authorized plan before deployment, verified backup and restoration.

## Event timestamps: explicit interpretation, no data rewrite

The API requires offset-bearing ISO 8601 dates for new/updated event dates and
returns UTC `Z` timestamps. Comparisons (upcoming/weekly) use UTC instants;
calendar boundaries use the browser-supplied IANA timezone (Los Angeles for
API callers that omit it), independently of the legacy storage convention.
The admin editor converts received instants into browser-local input values
before editing, and submits an offset-bearing UTC instant.

The existing DATETIME column is unchanged. There is no safe way to infer whether
an old naive timestamp meant UTC or Los Angeles wall time. The owner must confirm
one consistent historical convention in a sanitized clone and explicitly set
`EVENT_STORAGE_TIMEZONE=UTC` or `America/Los_Angeles`. No default is inferred.
New events are encoded in that confirmed storage convention; stored legacy
values are interpreted without rewriting them. New/empty databases should use
UTC. A mixed-convention legacy database REQUIRES a separately approved per-row
reconciliation/data-conversion plan. Do not select one timezone to hide mixed
semantics. Local ambiguous fall-back or nonexistent spring-forward wall times
are rejected with a controlled 503 rather than guessed. This includes new local
storage values that cannot round-trip uniquely; UTC storage avoids that limit.

Before traffic on a sanitized clone, with reviewed configuration:

    python -m flask --app main release-event-audit

This read-only command reports counts only and fails on ambiguous/nonexistent
stored times. It cannot prove the owner's historical convention. Missing timezone
configuration makes readiness fail (503). No command here changes timestamps.
Any timestamp repair/conversion requires separate owner approval and a verified
backup/restore plan; none was performed during these fixes.

## Avatars: bounded canonical raster in existing MySQL TEXT

The server accepts only a valid JPG/PNG/GIF/WebP base64 image data URL, at most
60,000 ASCII bytes including prefix, with dimensions at most 400x400. Pillow
validates decoded content and emits a single JPEG frame, discarding metadata and
appended content. Re-encoded output must also fit 60,000 bytes, below MySQL TEXT's
65,535-byte limit. SVG, external URLs, invalid/mismatched data, oversized encodings
and images are rejected with 400, atomically with other profile changes. Null
still clears a photo. The browser resizes new selections to 160px JPEG and checks
its upload budget; server validation remains authoritative. Old stored avatar
values are not mutated automatically. Review any oversized old rows in a
sanitized MySQL clone before adopting/altering a schema. No MEDIUMTEXT change or
production data migration is proposed. Install the pinned Pillow dependency.

## Input and migration adoption

Event and volunteer writes accept objects with only supported fields and bounded
text/types; calendar and volunteer list queries reject invalid ranges with 400.
Validation completes before mutation. Existing authorization is enforced first.
Volunteer submission no longer logs submitted email addresses.

Migration 0002 accepts SQLite INTEGER affinity and MySQL TINYINT(1)/reflected
widthless TINYINT for Boolean columns only when stored values are 0/1. Native
Boolean is also accepted. Widthless MySQL reflection is not itself proof: the
schema-only engine rehearsal and owner confirmation remain mandatory. Unknown
columns, constraints, other type drift or invalid values still halt adoption
before feature DDL; no stamping or coercion is used. All existing nullability,
index and FK checks remain. Existing installations already at revision 0002 do
not rerun this migration. This correction does not add a revision or authorize
schema changes; apply the existing migrations only under the original approved
operator procedure on the actual engine's sanitized clone first.

## Recovery and production gates

Destructive downgrade remains disabled. Back up DB plus uploads/config together,
restore to a NEW isolated target, and validate foreign keys, timestamps and
application compatibility before approving recovery. Older vulnerable code is
not an acceptable automatic rollback artifact. Current code, local tests and
static MySQL checks do not certify Linux hosting, actual MySQL compatibility,
SMTP, external providers, TLS/CORS/cookies, privacy retention or restored volumes.
Historical exposures still require repository/project owner remediation. No
production data, keys, permissions, Actions/Pages or infrastructure was changed.
