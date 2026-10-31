"""Exercise every registered API method anonymously with synthetic/missing input.
External services are unavailable; access-control success is never inferred from UI.
"""
import re
import pytest
import requests
from app import db
from app.config import Config


def test_all_api_routes_fail_safely_and_privileged_routes_deny_guests(app,monkeypatch,record_testsuite_property):
    def offline(*args,**kwargs):raise requests.ConnectionError('Synthetic offline provider')
    monkeypatch.setattr(requests.sessions.Session,'request',offline)
    report=[]
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api/'):continue
        path=re.sub(r'<int:[^>]+>','1',rule.rule)
        path=re.sub(r'<(?:[^:>]+:)?[^>]+>','home',path)
        for method in sorted(set(rule.methods)-{'OPTIONS','HEAD'}):
            # No writes carry credentials or real identity; privileged requests must deny.
            client=app.test_client()
            response=client.open(path,method=method,json={} if method not in ('GET','HEAD') else None)
            report.append((method,path,response.status_code))
            assert response.status_code!=500,(method,path,response.data[:120])
            if path.startswith(('/api/admin/','/api/security/')) and path not in ('/api/admin/login','/api/admin/logout'):
                if response.status_code==302:
                    assert response.headers['Location'].startswith('/api/admin/login')
                else:
                    assert response.status_code in (401,403,429),(method,path,response.status_code)
    assert report
    record_testsuite_property('api_methods_audited',len(report))
