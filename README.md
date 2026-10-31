# PNEC isolated review snapshot

This directory contains source only, with no Git history, production secrets,
user data, deployment workflows or active custom-domain/server configuration.
Do not publish or deploy without separate approval. See SOURCE-NOTES.md.
Use loopback-only local previews and synthetic tests; do not point at production.
The frontend uses reserved .invalid review API fallbacks outside localhost.
Private service credentials belong outside source control. Safe examples are
provided; never overwrite an existing environment. Read SECURITY.md before review.

## Validate locally

Use a separate Python environment with backend requirements plus frontend
requirements-dev.txt installed; no environment or dependency directory is bundled.
From the backend snapshot, run `python -B -m pytest -q -p no:cacheprovider`.
From any temporary working directory, run:

```sh
python -B /path/frontend/scripts/run-release-tests.py --frontend-root /path/frontend --backend-root /path/backend
```

The runner creates disposable build/state outside source. It blocks external APIs;
its responsive test blocks ALL external requests. Keep the local preview on loopback.
The frontend also has four offline unit suites: run `npm test` with Node installed.
No npm dependency installation is required. Ruby dependencies are pinned in the
frontend Gemfile/Gemfile.lock; `bundle check` validates an installed environment.
No production workflow, server config, credentials or deployment helper is present.

## Known review limitations

The optional preparedness RPG wrapper is included, but two legacy game engines
are absent upstream and the mansion-game classroom fallback is excluded pending
PNEC scope approval. See frontend RPG-LIMITATIONS.md and the external validation
report. Do not claim gameplay completeness from the quiz regression.
The offline responsive suite retains its desktop negative-margin assertion; it
fails with 0px because the external WordPress theme is not fetched. Twelve
viewport width/video bounds checks pass. External-theme visual equivalence and
live provider/SMTP/production database behavior are NOT certified.

## Publication boundary

These are file snapshots with no Git history, not yet GitHub repositories.
Publishing requires separate approval after the manifest/hash review and GitHub
App/automation scope confirmation. Do not copy deployment workflows or CNAME into
a new default branch: an initial push could otherwise run main-triggered jobs.
Keep future review repositories private, Actions disabled, Pages unconfigured,
and production credentials/integrations absent. No merge or deployment is approved.
