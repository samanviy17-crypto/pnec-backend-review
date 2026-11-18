"""HTTP checks inside the disposable container only; prints no credentials."""
import json
import os
import secrets
from http.cookies import SimpleCookie
from urllib.request import Request, urlopen
from urllib.error import HTTPError

assert os.environ.get('PNEC_DOCKER_DISPOSABLE_TEST') == 'true', 'Disposable container only'
ORIGIN = 'https://powaynec.opencodingsociety.com'
BASE = 'http://127.0.0.1:8475'
cookies = {}

def request(path, method='GET', data=None, headers=None):
    values = {'Origin': ORIGIN, **(headers or {})}
    values = {key:value for key,value in values.items() if value is not None}
    if cookies:
        values['Cookie'] = '; '.join(f'{k}={v}' for k, v in cookies.items())
    if data is not None:
        values['Content-Type'] = 'application/json'
    req = Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers=values, method=method)
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as error:
        response = error
    for value in response.headers.get_all('Set-Cookie', []):
        parsed = SimpleCookie(); parsed.load(value)
        for key, morsel in parsed.items():
            if not morsel.value:
                cookies.pop(key, None)
                continue
            assert morsel['secure'] and morsel['httponly'], 'Secure cookie policy required'
            cookies[key] = morsel.value
    body = response.read()
    return response.code, json.loads(body) if body else {}, response.headers

assert request('/api/health')[0] == 200
assert request('/api/ready')[1]['status'] == 'ready'
code, _, headers = request('/api/auth/profile', 'OPTIONS', headers={'Access-Control-Request-Method':'PATCH','Access-Control-Request-Headers':'Content-Type,X-CSRF-Token'})
assert code == 200 and headers['Access-Control-Allow-Origin'] == ORIGIN
assert headers['Access-Control-Allow-Credentials'] == 'true'
assert 'PATCH' in headers['Access-Control-Allow-Methods']
assert request('/api/auth/register', 'POST', {'email': secrets.token_hex(8)+'@example.test', 'display_name':'Synthetic Docker Resident', 'password':secrets.token_urlsafe(24)})[0] == 201
assert request('/api/auth/me')[0] == 200
assert request('/api/auth/profile', 'PATCH', {'bio':'Rejected missing CSRF'}, headers={'Origin':None})[0] == 403
token = request('/api/auth/csrf')[1]['csrf_token']
assert request('/api/auth/profile','PATCH',{'bio':'Synthetic Docker check'},headers={'Origin':None,'X-CSRF-Token':token})[0] == 200
assert request('/api/auth/profile','PATCH',{'bio':'Rejected origin'},headers={'Origin':'https://untrusted.example','X-CSRF-Token':token})[0] == 403
assert request('/api/announcements','POST',{'message':'Denied resident'})[0] == 403
assert request('/api/auth/logout','POST',{})[0] == 200
assert request('/api/auth/me')[0] == 401
print('PASS: health, readiness/migrations, exact-origin credentialed CORS, registration/session, cookie flags, CSRF, resident authorization, logout. HTTP cookies sent explicitly for this probe; browser HTTPS remains a release check.')
