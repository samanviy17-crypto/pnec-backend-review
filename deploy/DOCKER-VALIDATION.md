# Docker preparation validation — 2026-11-17

Reviewed on `feature/pnec-production-preparation-20261117` with Adya’s assigned port 8630. The tests used disposable SQLite state and synthetic accounts. No production database, credentials or server were used.

| Check | Result |
|---|---|
| Backend pytest | 213 passed on macOS with Python 3.14, with 7,953 deprecation warnings. Nine container startup tests cover port reporting, admission, unsafe configuration, missing state directories and refusal to create a missing SQLite file. |
| Native dependencies | `python -m pip check` passed. |
| Review startup | `scripts/check-review-startup.py` passed with native Gunicorn, fresh migrations and seed, health, readiness and exact review CORS and health reporting of the separate review listener. |
| Native disposable startup and HTTP | Gunicorn bound to `127.0.0.1:8630` and imported the disposable factory in a temporary directory. Migrations through `0002_announcements`, the production startup gate, readiness probe, credentialed CORS, registration, session and cookie flags, CSRF, resident authorization and logout passed. The HTTP probe explicitly forwards secure cookies. Browser HTTPS remains unverified. |
| Compose configuration | Standalone Docker Compose v5.8.0 `config --quiet` passed for both files. Both resolved to `127.0.0.1:8630:8630` with the default local settings. The production definition used a synthetic env file and temporary data path. The entrypoint accepted 8630 and rejected the previous port. |
| Source checks | Shell syntax, Python syntax and Git whitespace checks passed. |
| Sensitive data review | Gitleaks found no matches in the worktree or feature changes. File and diff review found no private env files, database copies, key files or production records in the reviewed changes. |

The machine had no Docker daemon. The Linux image build and dependency check, effective build-context filtering, Compose build/up, container Gunicorn startup and health transitions, non-root and tmpfs/bind-mount behavior, in-image pytest, and disposable project teardown remain unverified.

Server-side nginx and TLS/browser checks, live port availability, server paths and ownership, and real database backup/restore rehearsal also remain unverified. See [OCS-DOCKER-HANDOFF.md](OCS-DOCKER-HANDOFF.md) for the Docker commands and server handoff.
