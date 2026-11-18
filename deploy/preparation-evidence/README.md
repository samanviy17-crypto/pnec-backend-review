# Backend production-preparation evidence

204 pytest tests passed with disposable SQLite/in-memory data and blocked external
providers. 7935 deprecation warnings remain. Tests include review-origin preservation,
production exact-origin/credentialed CORS and all required methods/CSRF headers,
secure host-only session/remember cookies, real registration/login/logout and role
rejection, frozen migration parity, backup/restore, fresh migration 0002, compatible
legacy adoption with identical retained rows, drift/constraint rejection and stale/
missing-table readiness rejection. See `backend-tests.txt` and the test source.

No production migrations, credential changes, server actions or external resident
records. MySQL execution and server nginx/systemd validation remain unverified.
The companion frontend's `deploy/preparation-evidence/` holds 10/10 integration and
actual loopback registration/privacy/volunteer/notification/persistence results.
