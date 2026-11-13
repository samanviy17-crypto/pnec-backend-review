# Separate Render Free review deployment

This supersedes the snapshot README's old prohibition on review workflows. It
does not authorize changes to production services, databases, DNS or credentials.

## Existing review service

Use only the existing `pnec-backend-review` service, ID
`srv-dbr8i7d6e07s73at2s1g`, at
`https://pnec-backend-review.onrender.com`. Do not create another service.

1. In Render, confirm this exact service uses this repository's `main` branch,
   plan **Free**, no disks and no external database. Compare its configuration
   with `render.yaml`; do not upgrade the plan or select a production service.
2. Keep the independent review-only signing key and admin password in Render.
   Use only `admin@example.test` and synthetic resident accounts; never copy
   production values or commit credentials.
3. Keep automatic deployment disabled. The start command is
   `sh scripts/start-review.sh`; health path is `/api/ready`.
4. Obtain the secret deploy hook from this exact service's Render Settings.
   Copy it directly into GitHub Actions secrets, never into source or logs.

No provider account is configured by these files. The Free service sleeps when
idle. SQLite, uploads and limiter state are disposable and reset on every start.
There is no SMTP or AI provider credential. This is a synthetic review service,
not durable resident hosting. Third-party-cookie restrictions may still affect
cross-site browser sessions; bearer-authenticated API flows remain available.

## GitHub configuration

In this backend repository, create repository Actions variables:

- `RENDER_REVIEW_SERVICE_ID`: `srv-dbr8i7d6e07s73at2s1g`.
- `REVIEW_API_URL`: `https://pnec-backend-review.onrender.com`.
- `REVIEW_DEPLOY_ENABLED`: `true` only after inspecting the destination above.

Create a secret, preferably in GitHub environment `review`:

- `RENDER_REVIEW_DEPLOY_HOOK`: the matching secret deploy hook URL.

Environment `review` may have a required reviewer. The enable variable must be a
repository variable because it gates job creation before environment loading.
If it is unset, or differs from the exact string `true`, the deploy job is
skipped even when validation passes. The deploy job needs successful validation
and uses environment `review`, retaining any required deployment approval.
Its environment URL is `REVIEW_API_URL`, which supplies the clickable backend
link in GitHub Actions; that link alone does not prove deployment succeeded.
Do not add a GitHub write token, production database or provider keys. Render
holds the Flask signing/admin secrets; GitHub holds only the review deploy hook.

Run **Deploy Backend Review (Render)** manually on `main`. It installs the real
requirements, runs the full pytest suite and the real Gunicorn/migration startup
smoke test before deployment. When not enabled, deployment is skipped. The hook
requests the exact checked commit. Public verification requires health/readiness,
the same commit SHA and exact CORS policy; a trigger alone is not a success.

## Frontend integration

After the backend is verified, set frontend repository variable
`PNEC_REVIEW_API_URL` to the same API root and manually run **Deploy Frontend Review
(GitHub Pages)**. The build checks public review health/readiness/CORS before
embedding it. Until then the frontend is explicitly a static preview.

`FRONTEND_URL` is the full Pages project URL so reset links retain the project
path. Production-mode CORS/CSRF allow only `https://samanviy17-crypto.github.io`.
An HTTP Origin has no path: this necessarily includes other project sites on
that same origin, and cannot be limited to `/pnec-frontend-review/` with CORS.

## Local verification

With requirements installed, use the existing test command:

```sh
python -B -m pytest -q -p no:cacheprovider
python -B scripts/check-review-startup.py
```

The startup check creates a fresh temporary SQLite database and random signing
key, migrates/seeds it, starts Gunicorn on loopback and checks health/readiness
and allowed/denied origins. It never opens a configured external database.
