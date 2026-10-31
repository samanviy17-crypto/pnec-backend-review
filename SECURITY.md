# PNEC security boundary

No inherited Git history, exposed Google keys, identity backups, resident uploads,
database files, environment secrets or deployment workflows are included. Manual
build/start/recovery helpers require explicit operator inputs and never publish
source or configure hosting. Defaults are reserved review origins; production fails
closed without explicit signing secret, persistent database and approved HTTPS
frontend origin. Keep repository publishing disabled and GitHub write credentials
unset. See DEPLOYMENT_HANDOFF.md for owner actions and production gates.

Old repositories/history may still contain exposed keys and private data. Creating
clean private review repositories did not revoke credentials or remove exposures
from existing public commits, forks or caches. Owner remediation remains required.
Never test or reuse exposed keys. Use independently provisioned server-only keys.

All current rehearsals use synthetic accounts and isolated SQLite. Uploaded media
requires a recognized format signature, random exclusive paths, authorization and
size bounds; delivered uploads are attachments with nosniff. This is not antivirus
or a full media decoder. The operator must set upload retention/access controls and
may add malware scanning according to the service's threat model.
