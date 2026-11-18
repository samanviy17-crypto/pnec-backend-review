"""Exercise the real review start command on loopback with fresh synthetic state."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

import requests

root = Path(__file__).resolve().parents[1]
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
environment = {k: v for k, v in os.environ.items() if k not in (
    'DATABASE_URL', 'DB_ENDPOINT', 'DB_USERNAME', 'DB_PASSWORD',
    'GITHUB_TOKEN', 'GITHUB_OWNER', 'GITHUB_REPO', 'ADMIN_PASSWORD')}
environment.update(PNEC_REVIEW_EPHEMERAL='true', SECRET_KEY=secrets.token_urlsafe(48),
                   FRONTEND_URL='https://samanviy17-crypto.github.io/pnec-frontend-review',
                   PORT=str(port))
with tempfile.TemporaryFile(mode='w+') as log:
    process = subprocess.Popen(['sh', 'scripts/start-review.sh'], cwd=root, env=environment,
                               stdout=log, stderr=subprocess.STDOUT)
    try:
        base = f'http://127.0.0.1:{port}'
        for attempt in range(60):
            if process.poll() is not None:
                log.seek(0)
                raise RuntimeError('Review startup failed:\n' + log.read()[-5000:])
            try:
                response = requests.get(base + '/api/ready', timeout=2)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Review startup timed out')
        origin = 'https://samanviy17-crypto.github.io'
        health = requests.get(base + '/api/health', headers={'Origin': origin}, timeout=5)
        assert health.status_code == 200 and health.json()['status'] == 'ok' and health.json()['port'] == port
        assert health.json()['review'] and health.json()['ephemeral_storage']
        assert health.headers['Access-Control-Allow-Origin'] == origin
        rejected = requests.get(base + '/api/health', headers={'Origin': 'https://powaynec.com'}, timeout=5)
        assert 'Access-Control-Allow-Origin' not in rejected.headers
        print('PASS: Gunicorn startup, fresh migrations/seed, health, readiness and exact review CORS')
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
