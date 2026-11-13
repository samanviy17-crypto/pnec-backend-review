"""Trigger only the configured Render review service and verify its exact revision."""
import os
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

service = os.environ.get('RENDER_REVIEW_SERVICE_ID', '')
base = os.environ.get('REVIEW_API_URL', '').rstrip('/')
hook = urlsplit(os.environ.get('RENDER_REVIEW_DEPLOY_HOOK', ''))
target = urlsplit(base)
sha = os.environ['GITHUB_SHA']
if not re.fullmatch(r'srv-[a-z0-9]+', service):
    raise SystemExit('Configure RENDER_REVIEW_SERVICE_ID for the separate review service.')
if (target.scheme != 'https' or not re.fullmatch(r'pnec-backend-review(?:-[a-z0-9]+)?\.onrender\.com', target.netloc)
        or target.path or target.query or target.fragment):
    raise SystemExit('REVIEW_API_URL must identify the separate pnec-backend-review Render service.')
query = parse_qs(hook.query)
if (hook.scheme != 'https' or hook.netloc != 'api.render.com'
        or hook.path != '/deploy/' + service or not query.get('key') or hook.fragment):
    raise SystemExit('Configure the matching Render review deploy hook secret.')
query['ref'] = [sha]
url = urlunsplit((hook.scheme, hook.netloc, hook.path, urlencode(query, doseq=True), ''))
try:
    result = requests.post(url, timeout=30, allow_redirects=False)
except requests.RequestException:
    raise SystemExit('Render deploy request failed; inspect the provider dashboard.') from None
if result.status_code not in (200, 202):
    raise SystemExit('Render refused the review deploy request (response omitted to protect hook).')
origin = 'https://samanviy17-crypto.github.io'
for attempt in range(40):
    try:
        health = requests.get(base + '/api/health', headers={'Origin': origin}, timeout=20)
        ready = requests.get(base + '/api/ready', timeout=20)
        if (health.status_code == 200 and health.json().get('status') == 'ok'
                and health.json().get('revision') == sha and health.json().get('review') is True
                and ready.status_code == 200):
            assert health.headers.get('Access-Control-Allow-Origin') == origin
            denied = requests.get(base + '/api/health', headers={'Origin': 'https://untrusted.example'}, timeout=20)
            assert 'Access-Control-Allow-Origin' not in denied.headers
            print('PASS: public review health, readiness, exact deployed commit and CORS')
            break
    except (requests.RequestException, ValueError):
        pass
    time.sleep(15)
else:
    raise SystemExit('Review deploy not verified: expected commit/health/readiness did not become available.')
