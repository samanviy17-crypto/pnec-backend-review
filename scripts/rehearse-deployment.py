"""Run real migration, seed and Gunicorn startup on disposable synthetic SQLite.
No production connection, external credentials or existing database is used.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen, Request

root=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix='pnec-startup-rehearsal-'))
os.chmod(work,0o700)
python=Path(sys.executable)
secret=secrets.token_hex(32);password=secrets.token_urlsafe(32)
environment={key:os.environ[key] for key in ('PATH','HOME','LANG','TMPDIR','SYSTEMROOT') if key in os.environ}
environment.update(PATH=str(python.parent)+os.pathsep+environment.get('PATH',''),PYTHONDONTWRITEBYTECODE='1',FLASK_ENV='production',SECRET_KEY=secret,FRONTEND_URL='https://pnec-review.invalid',DATABASE_URL='sqlite:///'+str(work/'application.db'),SECURITY_STATE_PATH=str(work/'limits.json'),UPLOAD_FOLDER=str(work/'uploads'),ADMIN_EMAIL='operator@example.test',ADMIN_PASSWORD=password,MAIL_DELIVERY='disabled',GITHUB_PUBLISH_ENABLED='false')
with (work/'migration.log').open('w') as log:
 for command in ([str(python),'-B','-m','flask','--app','main:app','db','upgrade'],[str(python),'-B','-m','flask','--app','main:app','release-seed','--approved']):
  subprocess.run(command,cwd=root,env=environment,check=True,stdout=log,stderr=subprocess.STDOUT)
with socket.socket() as sock:
 sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
environment.update(PORT=str(port),BIND_ADDRESS='127.0.0.1',WEB_CONCURRENCY='2')
base=f'http://127.0.0.1:{port}'

def call(path,body=None,token=None):
 headers={'Origin':'https://pnec-review.invalid'}
 if body is not None:headers['Content-Type']='application/json'
 if token:headers['Authorization']='Bearer '+token
 request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
 with urlopen(request,timeout=5) as response:return response.status,json.load(response)

with (work/'gunicorn.log').open('w') as log:
 process=subprocess.Popen(['sh',str(root/'scripts/start-production.sh')],cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT)
 try:
  for attempt in range(100):
   if process.poll() is not None:raise RuntimeError('Gunicorn startup failed; inspect local evidence')
   try:
    if call('/api/ready')[0]==200:break
   except OSError:time.sleep(.1)
  else:raise RuntimeError('Startup readiness timed out')
  with (work/'smoke.log').open('w') as smoke_log:
   subprocess.run([str(python),'-B',str(root/'scripts/deployment-smoke.py'),'--base-url',base],env=environment,cwd=root,stdout=smoke_log,stderr=subprocess.STDOUT,check=True)
  assert call('/api/health')[0]==200
  status,auth=call('/api/auth/login',{'email':'operator@example.test','password':password,'remember':False})
  assert status==200 and auth['user']['role']=='admin'
  token=auth['token']
  assert call('/api/auth/me',token=token)[0]==200
  assert call('/api/announcements')[0]==200
  assert call('/api/chat/analytics',token=token)[0]==200
  assert call('/api/auth/logout',{},token)[0]==200
  result={'status':'PASS','bind':'loopback only','workers':2,'migration_head':'0002_pnec_features','health':200,'ready':200,'login_profile_analytics_logout':'PASS','production_access':False}
 finally:
  process.terminate()
  try:process.wait(timeout=15)
  except subprocess.TimeoutExpired:process.kill();process.wait()
with (work/'recovery.log').open('w') as recovery_log:
 for source,destination in [(work/'application.db',work/'backup.db'),(work/'backup.db',work/'restored.db')]:
  subprocess.run([str(python),'-B',str(root/'scripts/sqlite_snapshot.py'),'--approved','--source',str(source),'--destination',str(destination)],env=environment,cwd=root,stdout=recovery_log,stderr=subprocess.STDOUT,check=True)
 environment['DATABASE_URL']='sqlite:///'+str(work/'restored.db')
 subprocess.run([str(python),'-B','-c',"from main import app; from app import db; from app.models.user import User; ctx=app.app_context(); ctx.push(); assert app.test_client().get('/api/ready').status_code==200; assert User.query.filter_by(email='operator@example.test').count()==1; print('Restored schema ready; synthetic admin preserved')"],env=environment,cwd=root,stdout=recovery_log,stderr=subprocess.STDOUT,check=True)
result.update(smoke_script='PASS',full_schema_backup_restore='PASS')
(work/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'evidence_directory':str(work),**result},indent=2))
