"""Offline filesystem gate for an uninitialized source snapshot; values never printed."""
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
pattern = re.compile(rb'(^|[^A-Za-z0-9_])(AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|(AKIA|ASIA)[A-Z0-9]{16}|gsk_[A-Za-z0-9]{30,}|sk-(proj-|ant-)?[A-Za-z0-9_-]{32,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----)', re.M)
findings = []
for path in root.rglob('*'):
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        findings.append(relative + ': symlink')
        continue
    if path.is_dir():
        if path.name in ('.git', '.github', '_site', 'node_modules', '__pycache__', '.venv'):
            findings.append(relative + ': history/automation/generated directory')
        continue
    if path.name == 'CNAME' or (path.name.startswith('.env') and path.name != '.env.example') or path.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.pem', '.key', '.pyc', '.log') or relative.startswith('instance/'):
        findings.append(relative + ': private/runtime/domain file')
    data = path.read_bytes()
    if pattern.search(data):
        findings.append(relative + ': credential signature')
    if path.suffix == '.json':
        try:
            document = json.loads(data)
        except (ValueError, UnicodeError):
            continue
        def has_identity(value):
            if isinstance(value, dict):
                if isinstance(value.get('email'), str) and '@' in value['email'] and any(isinstance(value.get(name), str) for name in ('uid', 'name', 'password_hash')):
                    return True
                return any(has_identity(item) for item in value.values())
            if isinstance(value, list):
                return any(has_identity(item) for item in value)
            return False
        if has_identity(document):
            findings.append(relative + ': identity-record shape requires review')
print('\n'.join(findings) if findings else 'PASS: no tested credential, identity, history, automation or private/runtime findings')
sys.exit(bool(findings))
