# Separate Render Free review deployment

This supersedes the snapshot README's old prohibition on review workflows. It
does not authorize changes to production services, databases, DNS or credentials.

## Configure the NEW review service

1. In Render, create a new Blueprint from this repository's `main` branch and
   inspect `render.yaml`. Confirm service name `pnec-backend-review`, plan **Free**,
   no disks, no databases and no existing production service selected. Do not
   upgrade the plan. The first provisioning deploy is performed by Render.
2. Supply a new, review-only `ADMIN_PASSWORD` (12+ characters) when prompted.
   Use only `admin@example.test` and synthetic resident accounts. The Blueprint
   generates an independent `SECRET_KEY`; never copy production values.
3. Keep automatic deployment disabled. The start command is
   `sh scripts/start-review.sh`; health path is `/api/ready`.
4. Record the actual `https://pnec-backend-review[-suffix].onrender.com` URL and
   service ID (`srv-...`). Obtain its secret deploy hook from Render Settings.

No provider account is configured by these files. The Free service sleeps when
idle. SQLite, uploads and limiter state are disposable and reset on every start.
There is no SMTP or AI provider credential. This is a synthetic review service,
not durable resident hosting. Third-party-cookie restrictions may still affect
cross-site browser sessions; bearer-authenticated API flows remain available.

## GitHub configuration

In this backend repository, create repository Actions variables:

- `RENDER_REVIEW_SERVICE_ID`: the NEW review service ID.
- `REVIEW_API_URL`: its actual HTTPS root URL, without a path.
- `REVIEW_DEPLOY_ENABLED`: `true` only after inspecting the destination above.

Create a secret, preferably in GitHub environment `review`:

- `RENDER_REVIEW_DEPLOY_HOOK`: the matching secret deploy hook URL.

Environment `review` may have a required reviewer. The enable variable must be a
repository variable because it gates job creation before environment loading.
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
