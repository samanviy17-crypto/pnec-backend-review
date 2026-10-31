"""Read-only smoke checks. Loopback only unless an operator explicitly opts in."""
import argparse,json
from urllib.parse import urlsplit
from urllib.request import urlopen
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--base-url',required=True)
p.add_argument('--allow-remote',action='store_true',help='Operator authorization required; never used during local readiness work')
a=p.parse_args();u=urlsplit(a.base_url)
if u.hostname not in ('127.0.0.1','localhost') and not a.allow_remote:p.error('Remote targets require explicit operator authorization')
if u.username or u.password or u.query or u.fragment:p.error('No credentials, query or fragment permitted')
for path,expected in [('/api/health','ok'),('/api/ready','ready'),('/api/announcements',None),('/api/preparedness/quiz',None),('/api/faq/categories',None),('/api/volunteer/tasks',None),('/api/supply-drives',None)]:
 with urlopen(a.base_url.rstrip('/')+path,timeout=10) as r:
  body=json.load(r);assert r.status==200
  if expected:assert body['status']==expected
 print('PASS',path)
