# Release migration and recovery

The canonical operator sequence is [DEPLOYMENT_HANDOFF.md](../DEPLOYMENT_HANDOFF.md).
No production actions are authorized by this documentation. The frozen additive
0001_pnec_release migration is preserved unchanged; 0002_pnec_features adds four
announcement/chat tables with inherited-table preflight validation. Head readiness
requires revision 0002_pnec_features and all 32 application tables.

Never rewrite or blindly stamp migrations. Test the actual sanitized production
schema in staging. Worker construction never initializes production databases.
Destructive downgrades are refused. SQLite DDL can partially persist after failure;
restore coordinated database/upload backups to NEW targets and validate them before
an operator-approved configuration/traffic switch. Existing files are never
overwritten by scripts/sqlite_snapshot.py. MySQL recovery requires the operator's
approved engine-specific tooling and rehearsal.
