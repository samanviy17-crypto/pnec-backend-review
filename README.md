# PNEC review and deployment-readiness source

This private review repository contains only PNEC source and safe examples.
Read [DEPLOYMENT_HANDOFF.md](DEPLOYMENT_HANDOFF.md) for the manual deployment
sequence, environment checklist, required operator checks and rollback procedure.
Read [VALIDATION_REPORT.md](VALIDATION_REPORT.md) for executed checks and limits.

No production deployment is authorized. No automatic deployment workflow is
included. Keep GitHub Actions disabled and GitHub Pages unconfigured during review.
Never add service credentials, resident data, database files or uploads to Git.

## Local validation

Use an isolated virtual environment with backend requirements and frontend
requirements-dev.txt installed. Tests use synthetic data. From the backend run:

```sh
python -B -m pytest -q -p no:cacheprovider
python -B scripts/rehearse-deployment.py
```

From the frontend, run offline Node unit tests with `npm test`, and:

```sh
python -B scripts/run-release-tests.py --frontend-root /absolute/frontend --backend-root /absolute/backend
```

The runner builds outside source, blocks external APIs and checks all 39 pages at
mobile/tablet/desktop widths. Dependencies are declared in requirements.txt and
Gemfile.lock; no dependency installation is bundled. Default builds use reserved
review origins; the manual production build requires explicit public origins and
contact email. Core resident workflows do not depend on the deferred RPG. The local
CSS foundation replaces runtime WordPress theme scripts, styles and Google fonts.

## Scope and deferred features

See RPG-LIMITATIONS.md in the frontend: missing legacy engines are not shipped.
Newsletter signup and unconfigured payment destinations are safely disabled.
Chat uses a server proxy; no browser service keys are supported. Live provider,
SMTP, actual production schema, target Linux and domain/TLS acceptance require an
operator's approved staging environment. Analytics does not silently upload local
browser conversations. See SOURCE-NOTES.md, ATTRIBUTION.md and LICENSE for provenance.
