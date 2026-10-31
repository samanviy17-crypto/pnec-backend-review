# Migration and rollback review — NOT a deployment procedure

Production is not authorized. Preserve the reviewed 0001_pnec_release additive
baseline: 28 application tables and Alembic revision state. Application workers do
not initialize production schema. Rehearse schema adoption and a single approved
seed job on a sanitized clone; unknown schema drift must stop for review.
SQLite synthetic coverage is not proof of MySQL compatibility. Back up database
and uploads consistently and rehearse restoration to a new target before any
production operation. Never drop schema, overwrite live resident data or blindly
stamp a revision. Destructive downgrade is deliberately refused. Validate a prior
secure application image against the additive schema; if incompatible, stop and
obtain a recovery-point/restore plan. No production Compose/nginx/Docker files,
remote-access helpers or credentials are included in this snapshot.
