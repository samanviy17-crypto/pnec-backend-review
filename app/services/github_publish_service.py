# app/services/github_publish_service.py
# v3.15 — commit file changes to a GitHub repo via the REST API.
#
# Used by the Live Theme Editor's "Publish to GitHub" button: admins
# edit pages in the browser, click Publish, and this service commits
# the changes to the public repo. Pages then rebuilds in ~5 min.
#
# Architecture:
#   - The editor stores draft content in the database (page_template etc.)
#   - When "Publish to GitHub" is clicked, the controller:
#       1. Collects the file path + new content for each file to update
#       2. Calls publish_files() here, which uses the GitHub REST API
#          to commit a single commit covering all changed files
#       3. Returns the commit SHA + the build-status URL
#
# Why direct API commits (not git clone+push):
#   - The Flask host doesn't need git installed or write access to a
#     working tree.
#   - One PAT token. One commit. Atomic.
#   - The PAT scope is narrow ("Contents: read+write" on the two
#     PNEC repos), much safer than a deploy SSH key.
#
# Auth header:
#   "Authorization: Bearer <GITHUB_TOKEN>"
#   (Fine-grained PATs work with Bearer; classic PATs work with both
#    "token <pat>" and "Bearer <pat>".)

import base64
import time
from typing import Iterable

import requests
from flask import current_app


GITHUB_API = 'https://api.github.com'
DEFAULT_TIMEOUT = 30


class GitHubPublishError(Exception):
    """Raised when GitHub returns a non-success status or the request
    couldn't be made (network, missing token, etc.)."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _config():
    """Return (token, owner, repo, branch) from app config; raise if
    token is missing — we never want to silently fail-open here."""
    cfg = current_app.config
    token = cfg.get('GITHUB_TOKEN')
    if not token:
        raise GitHubPublishError('GITHUB_TOKEN not configured on the server.')
    return (
        token,
        cfg.get('GITHUB_OWNER') or 'whitelunarium',
        cfg.get('GITHUB_REPO')  or 'Beasts_FrontEnd',
        cfg.get('GITHUB_BRANCH') or 'main',
    )


def _hdrs(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'PNEC-Live-Editor/3.15',
    }


def get_file(path: str):
    """Fetch the current content + sha for `path` on the configured
    branch. Returns (content_str, sha) or (None, None) if 404."""
    token, owner, repo, branch = _config()
    url = f'{GITHUB_API}/repos/{owner}/{repo}/contents/{path}'
    r = requests.get(url, headers=_hdrs(token),
                     params={'ref': branch}, timeout=DEFAULT_TIMEOUT)
    if r.status_code == 404:
        return None, None
    if not r.ok:
        raise GitHubPublishError(
            f'GET contents/{path} failed', r.status_code, r.text[:300]
        )
    data = r.json()
    if data.get('type') != 'file':
        raise GitHubPublishError(f'{path} is not a file (type={data.get("type")})')
    encoded = (data.get('content') or '').replace('\n', '')
    try:
        content = base64.b64decode(encoded).decode('utf-8')
    except Exception:
        content = ''
    return content, data.get('sha')


def commit_single_file(path: str, new_content: str, message: str,
                        committer_name: str = None, committer_email: str = None,
                        expected_sha: str = None):
    """Commit a SINGLE file change. Simpler than multi-file commits
    (uses the Contents API), works well for single-page edits.

    If `expected_sha` is provided, raises GitHubPublishError if the
    file's current SHA on the branch doesn't match — protects against
    two admins overwriting each other's work in the editor. The error
    has a special status of 409 (conflict).

    Returns dict { commit_sha, html_url, content_sha, branch }."""
    token, owner, repo, branch = _config()
    _, existing_sha = get_file(path)

    # Concurrent-edit conflict check
    if expected_sha and existing_sha and existing_sha != expected_sha:
        raise GitHubPublishError(
            f'File changed on the branch since you loaded it. '
            f'Someone else may have committed an edit to {path}. '
            f'Reload the file to see their changes, then merge your '
            f'edits.',
            status=409,
            body=f'expected={expected_sha[:8]} actual={existing_sha[:8]}',
        )

    encoded = base64.b64encode(new_content.encode('utf-8')).decode('ascii')
    body = {
        'message': message,
        'content': encoded,
        'branch': branch,
    }
    if existing_sha:
        body['sha'] = existing_sha
    if committer_name and committer_email:
        body['committer'] = {'name': committer_name, 'email': committer_email}

    url = f'{GITHUB_API}/repos/{owner}/{repo}/contents/{path}'
    r = requests.put(url, headers=_hdrs(token), json=body, timeout=DEFAULT_TIMEOUT)
    if not r.ok:
        # GitHub itself returns 409 if the SHA in the body doesn't
        # match the current branch HEAD — happens in a tight race
        # between our get_file() and our PUT.
        if r.status_code == 409:
            raise GitHubPublishError(
                f'File changed on the branch during publish. '
                f'Reload the file and try again.',
                status=409, body=r.text[:300],
            )
        raise GitHubPublishError(
            f'PUT contents/{path} failed', r.status_code, r.text[:500]
        )
    data = r.json()
    return {
        'commit_sha':  (data.get('commit') or {}).get('sha'),
        'html_url':    (data.get('commit') or {}).get('html_url'),
        'content_sha': (data.get('content') or {}).get('sha'),
        'branch':      branch,
    }


def commit_multiple_files(files: Iterable[dict], message: str,
                          committer_name: str = None,
                          committer_email: str = None):
    """Commit multiple files in ONE atomic commit.

    Each item in `files` is a dict: { path, content[, binary] }.
    - If `binary` is True, `content` must be raw bytes (or a
      latin-1-decoded string of those bytes).
    - Otherwise `content` is a UTF-8 string.

    Uses the lower-level Git Data API (Tree / Blob / Commit / Ref).

    Returns dict { commit_sha, tree_sha, html_url, branch, count }."""
    token, owner, repo, branch = _config()
    files = list(files)
    if not files:
        raise GitHubPublishError('No files to commit.')

    repo_base = f'{GITHUB_API}/repos/{owner}/{repo}'
    h = _hdrs(token)

    # 1. Resolve the branch HEAD (the SHA of the latest commit on `branch`)
    r = requests.get(f'{repo_base}/git/refs/heads/{branch}', headers=h, timeout=DEFAULT_TIMEOUT)
    if not r.ok:
        raise GitHubPublishError(
            f'GET refs/heads/{branch} failed', r.status_code, r.text[:300]
        )
    head_sha = r.json()['object']['sha']

    # 2. Get the tree SHA for the head commit
    r = requests.get(f'{repo_base}/git/commits/{head_sha}', headers=h, timeout=DEFAULT_TIMEOUT)
    if not r.ok:
        raise GitHubPublishError(
            f'GET commits/{head_sha} failed', r.status_code, r.text[:300]
        )
    base_tree = r.json()['tree']['sha']

    # 3. Create a blob per file
    tree_entries = []
    for f in files:
        path = f.get('path')
        content = f.get('content', '')
        is_binary = bool(f.get('binary'))
        if not path:
            raise GitHubPublishError('file dict missing path')
        # Encode as base64 so we can carry arbitrary content. For binary
        # files the caller passes bytes (or latin-1-decoded bytes) — we
        # round-trip those without UTF-8 corruption.
        if is_binary:
            if isinstance(content, str):
                # Treat as latin-1 bytes so we don't UTF-8 corrupt
                raw = content.encode('latin-1')
            else:
                raw = bytes(content)
        else:
            raw = content.encode('utf-8')
        encoded = base64.b64encode(raw).decode('ascii')
        r = requests.post(f'{repo_base}/git/blobs', headers=h, timeout=DEFAULT_TIMEOUT,
                          json={'content': encoded, 'encoding': 'base64'})
        if not r.ok:
            raise GitHubPublishError(
                f'POST blobs (path={path}) failed', r.status_code, r.text[:300]
            )
        tree_entries.append({
            'path': path,
            'mode': '100644',
            'type': 'blob',
            'sha':  r.json()['sha'],
        })

    # 4. Create a tree based on the existing tree + our new blobs
    r = requests.post(f'{repo_base}/git/trees', headers=h, timeout=DEFAULT_TIMEOUT,
                      json={'base_tree': base_tree, 'tree': tree_entries})
    if not r.ok:
        raise GitHubPublishError(
            'POST trees failed', r.status_code, r.text[:300]
        )
    tree_sha = r.json()['sha']

    # 5. Create the commit object
    commit_body = {
        'message': message,
        'tree': tree_sha,
        'parents': [head_sha],
    }
    if committer_name and committer_email:
        commit_body['author'] = {'name': committer_name, 'email': committer_email,
                                 'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        commit_body['committer'] = commit_body['author']

    r = requests.post(f'{repo_base}/git/commits', headers=h, timeout=DEFAULT_TIMEOUT,
                      json=commit_body)
    if not r.ok:
        raise GitHubPublishError(
            'POST commits failed', r.status_code, r.text[:300]
        )
    commit_sha = r.json()['sha']
    commit_html = r.json().get('html_url')

    # 6. Update the branch ref to point at our new commit
    r = requests.patch(f'{repo_base}/git/refs/heads/{branch}', headers=h, timeout=DEFAULT_TIMEOUT,
                       json={'sha': commit_sha, 'force': False})
    if not r.ok:
        raise GitHubPublishError(
            f'PATCH refs/heads/{branch} failed', r.status_code, r.text[:500]
        )

    return {
        'commit_sha':  commit_sha,
        'tree_sha':    tree_sha,
        'html_url':    commit_html,
        'branch':      branch,
        'count':       len(files),
    }


def workflow_runs(per_page: int = 5):
    """Return the most-recent Pages-deploy workflow runs so the UI can
    surface 'Pages is rebuilding'. Returns [] if anything fails — this
    is a nice-to-have, not a must."""
    try:
        token, owner, repo, _branch = _config()
        url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs'
        r = requests.get(url, headers=_hdrs(token), timeout=DEFAULT_TIMEOUT,
                         params={'per_page': per_page})
        if not r.ok:
            return []
        return r.json().get('workflow_runs', []) or []
    except Exception:
        return []


def file_history(path: str, per_page: int = 10):
    """Recent commits for a single file. Returns list of dicts or []."""
    try:
        token, owner, repo, branch = _config()
        url = f'{GITHUB_API}/repos/{owner}/{repo}/commits'
        r = requests.get(url, headers=_hdrs(token), timeout=DEFAULT_TIMEOUT,
                         params={'path': path, 'sha': branch, 'per_page': per_page})
        if not r.ok:
            return []
        out = []
        for c in r.json() or []:
            cmt = c.get('commit') or {}
            author = cmt.get('author') or {}
            out.append({
                'sha':         c.get('sha'),
                'short_sha':   (c.get('sha') or '')[:7],
                'message':     (cmt.get('message') or '').split('\n')[0][:200],
                'author_name': author.get('name'),
                'author_date': author.get('date'),
                'html_url':    c.get('html_url'),
            })
        return out
    except Exception:
        return []


def get_file_at(path: str, ref: str):
    """Fetch a file's content + sha at a specific ref (commit sha or
    branch name). Used by /diff and rollback. Returns (content, sha) or
    (None, None) on 404."""
    token, owner, repo, _branch = _config()
    url = f'{GITHUB_API}/repos/{owner}/{repo}/contents/{path}'
    r = requests.get(url, headers=_hdrs(token), params={'ref': ref},
                     timeout=DEFAULT_TIMEOUT)
    if r.status_code == 404:
        return None, None
    if not r.ok:
        raise GitHubPublishError(
            f'GET contents/{path}@{ref} failed', r.status_code, r.text[:300]
        )
    data = r.json()
    if data.get('type') != 'file':
        raise GitHubPublishError(f'{path}@{ref} is not a file')
    import base64 as _b64
    encoded = (data.get('content') or '').replace('\n', '')
    try:
        content = _b64.b64decode(encoded).decode('utf-8')
    except Exception:
        content = ''
    return content, data.get('sha')


def list_directory(path: str = 'pages'):
    """List files in `path` (default: 'pages') at the configured branch.

    Returns a list of {path, name, sha, size, type} dicts — type is
    'file' or 'dir'. Used by /api/admin/publish/pages so the Site Nav
    Manager can offer newly-created admin pages as nav suggestions
    without having to ship a hardcoded catalog on the frontend.

    Empty list for 404 (missing directory) — same shape as get_file.
    """
    token, owner, repo, branch = _config()
    safe_path = path.strip('/').replace('..', '')
    url = f'{GITHUB_API}/repos/{owner}/{repo}/contents/{safe_path}'
    r = requests.get(url, headers=_hdrs(token),
                     params={'ref': branch}, timeout=DEFAULT_TIMEOUT)
    if r.status_code == 404:
        return []
    if not r.ok:
        raise GitHubPublishError(
            f'GET contents/{safe_path} failed', r.status_code, r.text[:300]
        )
    data = r.json()
    if not isinstance(data, list):
        # GitHub returns a single dict for files; only directories
        # come back as arrays. Anything else here is a config error.
        return []
    return [
        {
            'path': entry.get('path'),
            'name': entry.get('name'),
            'sha':  entry.get('sha'),
            'size': entry.get('size'),
            'type': entry.get('type'),
        }
        for entry in data
        if entry.get('name') and not entry['name'].startswith('.')
    ]


def repo_info():
    """Lightweight health check — confirm token + repo are reachable.

    Returns a dict {ok, owner, repo, branch, name, default_branch,
    private, ...} or raises GitHubPublishError."""
    token, owner, repo, branch = _config()
    url = f'{GITHUB_API}/repos/{owner}/{repo}'
    r = requests.get(url, headers=_hdrs(token), timeout=DEFAULT_TIMEOUT)
    if not r.ok:
        raise GitHubPublishError(
            f'GET repos/{owner}/{repo} failed', r.status_code, r.text[:300]
        )
    j = r.json()
    return {
        'ok':            True,
        'owner':         owner,
        'repo':          repo,
        'branch':        branch,
        'full_name':     j.get('full_name'),
        'default_branch': j.get('default_branch'),
        'private':       j.get('private'),
        'pushed_at':     j.get('pushed_at'),
        'html_url':      j.get('html_url'),
    }
