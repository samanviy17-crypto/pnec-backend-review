# app/routes/admin.py
# Responsibility: Admin API endpoints plus a minimal server-rendered admin UI.

from flask import Blueprint, request, jsonify, redirect, url_for, render_template_string
from flask_login import current_user, login_user, logout_user
from app.models.user import User
from app.services.operations_service import get_operations_snapshot
from app.services.auth_service import update_user_role, authenticate_user
from app.utils.errors import error_response
from app.utils.auth_decorators import requires_role, requires_min_role

admin_bp = Blueprint('admin', __name__)

_ADMIN_LOGIN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PNEC Admin Login</title>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #121c31;
      --line: rgba(255,255,255,0.12);
      --text: #ebf2ff;
      --muted: #9bb0d1;
      --accent: #72af2f;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      font-family: Arial, sans-serif;
      background: linear-gradient(180deg, #08111f 0%, #0f1b31 100%);
      color: var(--text);
    }
    .card {
      width: min(440px, 100%);
      padding: 28px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      box-shadow: 0 24px 60px rgba(0,0,0,0.28);
    }
    h1 { margin: 0 0 8px; font-size: 2rem; }
    p { color: var(--muted); margin: 0 0 20px; }
    label { display: block; margin: 0 0 8px; font-weight: 700; }
    input {
      width: 100%;
      margin: 0 0 16px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #0b1427;
      color: var(--text);
    }
    button {
      width: 100%;
      border: 0;
      border-radius: 10px;
      padding: 12px 14px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    .error {
      margin: 0 0 16px;
      padding: 12px 14px;
      border-radius: 10px;
      background: rgba(239,68,68,0.12);
      border: 1px solid rgba(239,68,68,0.35);
      color: #fecaca;
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>Admin Login</h1>
    <p>Sign in with an admin account to view backend user accounts.</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="post">
      <input type="hidden" name="next" value="{{ next_url }}">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" autocomplete="email" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Sign In</button>
    </form>
  </main>
</body>
</html>
"""

_ADMIN_ACCOUNTS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PNEC Admin Accounts</title>
  <style>
    :root {
      --bg: #09111f;
      --panel: #101b31;
      --line: rgba(255,255,255,0.12);
      --text: #edf3ff;
      --muted: #9cb1d2;
      --accent: #72af2f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      padding: 24px;
      font-family: Arial, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #08111f 0%, #0f1a2f 100%);
    }
    .shell { max-width: 1200px; margin: 0 auto; }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
    }
    .title h1 { margin: 0 0 6px; }
    .title p { margin: 0; color: var(--muted); }
    .actions a {
      display: inline-block;
      text-decoration: none;
      color: white;
      background: var(--accent);
      padding: 10px 14px;
      border-radius: 10px;
      font-weight: 700;
      margin-left: 8px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-size: 0.9rem; }
    tr:last-child td { border-bottom: 0; }
    .meta {
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .role {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(114,175,47,0.15);
      border: 1px solid rgba(114,175,47,0.35);
    }
    .status-badge {
      display: inline-block;
      min-width: 76px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 700;
      text-align: center;
    }
    .status-active {
      color: #dff8e8;
      background: rgba(39,174,96,0.16);
      border: 1px solid rgba(39,174,96,0.45);
    }
    .status-inactive {
      color: #ffd8d1;
      background: rgba(192,57,43,0.16);
      border: 1px solid rgba(192,57,43,0.45);
    }
    tr.inactive-row td {
      color: #aab6c7;
      background: rgba(255,255,255,0.025);
    }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 16px;
    }
    .filters a {
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.04);
      font-weight: 700;
      font-size: 0.86rem;
    }
    .filters a.active {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    @media (max-width: 900px) {
      body { padding: 12px; }
      .panel { overflow-x: auto; }
      table { min-width: 900px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div class="title">
        <h1>Backend Accounts</h1>
        <p>Viewing the real users stored in the Flask backend database.</p>
      </div>
      <div class="actions">
        <a href="{{ url_for('admin.admin_operations_page') }}">Operations Dashboard</a>
        <a href="{{ url_for('admin.admin_logout_page') }}">Logout</a>
      </div>
    </div>
    <p class="meta">Signed in as {{ current_user.email }}. Total accounts: {{ total_count }} · Active: {{ active_count }} · Inactive: {{ inactive_count }}</p>
    <nav class="filters" aria-label="Account status filters">
      <a href="{{ url_for('admin.admin_accounts_page') }}" class="{{ 'active' if status_filter == 'all' else '' }}">All</a>
      <a href="{{ url_for('admin.admin_accounts_page', status='active') }}" class="{{ 'active' if status_filter == 'active' else '' }}">Active</a>
      <a href="{{ url_for('admin.admin_accounts_page', status='inactive') }}" class="{{ 'active' if status_filter == 'inactive' else '' }}">Inactive</a>
    </nav>
    <section class="panel">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Email</th>
            <th>Display Name</th>
            <th>Role</th>
            <th>Active</th>
            <th>Neighborhood</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {% if not users %}
          <tr>
            <td colspan="7" style="text-align:center;color:var(--muted);padding:28px;">No accounts match this filter.</td>
          </tr>
          {% endif %}
          {% for user in users %}
          <tr class="{{ 'inactive-row' if not user.is_active else '' }}">
            <td>{{ user.id }}</td>
            <td>{{ user.email }}</td>
            <td>{{ user.display_name }}</td>
            <td><span class="role">{{ user.role }}</span></td>
            <td>
              <span class="status-badge {{ 'status-active' if user.is_active else 'status-inactive' }}">
                {{ 'Active' if user.is_active else 'Inactive' }}
              </span>
            </td>
            <td>{{ user.neighborhood_id if user.neighborhood_id is not none else '—' }}</td>
            <td>{{ user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else '—' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""

_ADMIN_OPERATIONS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PNEC Operations Dashboard</title>
  <style>
    :root {
      --bg: #09111f;
      --panel: #101b31;
      --line: rgba(255,255,255,0.12);
      --text: #edf3ff;
      --muted: #9cb1d2;
      --accent: #72af2f;
      --warn: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      padding: 24px;
      font-family: Arial, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #08111f 0%, #0f1a2f 100%);
    }
    .shell { max-width: 1280px; margin: 0 auto; }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
    }
    .title h1 { margin: 0 0 6px; }
    .title p { margin: 0; color: var(--muted); }
    .actions a {
      display: inline-block;
      text-decoration: none;
      color: white;
      background: var(--accent);
      padding: 10px 14px;
      border-radius: 10px;
      font-weight: 700;
      margin-left: 8px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-size: 0.9rem; }
    tr:last-child td { border-bottom: 0; }
    .chip {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 12px;
      border: 1px solid transparent;
    }
    .chip-immediate { background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.35); }
    .chip-high { background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.35); }
    .chip-moderate { background: rgba(59,130,246,0.14); border-color: rgba(59,130,246,0.28); }
    .chip-stable { background: rgba(114,175,47,0.15); border-color: rgba(114,175,47,0.35); }
    @media (max-width: 960px) {
      body { padding: 12px; }
      .panel { overflow-x: auto; }
      table { min-width: 980px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div class="title">
        <h1>Volunteer + Resource Optimization</h1>
        <p>Neighborhood pressure scores combine resident load, zone severity, volunteer coverage, and supply inventory.</p>
      </div>
      <div class="actions">
        <a href="{{ url_for('admin.admin_accounts_page') }}">Accounts</a>
        <a href="{{ url_for('admin.admin_logout_page') }}">Logout</a>
      </div>
    </div>
    <section class="panel">
      <table>
        <thead>
          <tr>
            <th>Neighborhood</th>
            <th>Zone</th>
            <th>Residents</th>
            <th>Volunteers</th>
            <th>Resource Units</th>
            <th>Pressure</th>
            <th>Priority</th>
            <th>Recommended Action</th>
          </tr>
        </thead>
        <tbody>
          {% for item in recommendations %}
          <tr>
            <td>#{{ item.number }} {{ item.name }}</td>
            <td>{{ item.zone or '—' }}</td>
            <td>{{ item.resident_count }}</td>
            <td>{{ item.volunteer_count }}</td>
            <td>{{ item.resource_units }}</td>
            <td>{{ item.pressure_score }}</td>
            <td>
              <span class="chip chip-{{ item.priority|lower }}">{{ item.priority }}</span>
            </td>
            <td>{{ item.recommended_action }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login_page():
    """Render and process a minimal admin login form for the backend admin UI."""
    next_url = request.args.get('next') or request.form.get('next') or url_for('admin.admin_accounts_page')

    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect(next_url)

    error = None
    if request.method == 'POST':
      email = (request.form.get('email') or '').strip()
      password = request.form.get('password') or ''

      user, err = authenticate_user(email, password)
      if err:
          error = 'Incorrect email or password.'
      elif user.role != 'admin':
          error = 'This page is only available to admin accounts.'
      else:
          login_user(user, remember=False)
          return redirect(next_url)

    return render_template_string(_ADMIN_LOGIN_TEMPLATE, error=error, next_url=next_url)


@admin_bp.route('/logout', methods=['GET'])
def admin_logout_page():
    """End the current backend admin session and return to the admin login page."""
    logout_user()
    return redirect(url_for('admin.admin_login_page'))


@admin_bp.route('/accounts', methods=['GET'])
def admin_accounts_page():
    """Render an admin-only server-side view of backend accounts."""
    if not current_user.is_authenticated:
        return redirect(url_for('admin.admin_login_page', next=request.path))
    if current_user.role != 'admin':
        logout_user()
        return redirect(url_for('admin.admin_login_page', next=request.path))

    status_filter = (request.args.get('status') or 'all').strip().lower()
    if status_filter not in ('all', 'active', 'inactive'):
        status_filter = 'all'

    query = User.query
    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'inactive':
        query = query.filter_by(is_active=False)

    users = query.order_by(User.created_at.desc()).all()
    total_count = User.query.count()
    active_count = User.query.filter_by(is_active=True).count()
    inactive_count = User.query.filter_by(is_active=False).count()

    return render_template_string(
        _ADMIN_ACCOUNTS_TEMPLATE,
        users=users,
        current_user=current_user,
        status_filter=status_filter,
        total_count=total_count,
        active_count=active_count,
        inactive_count=inactive_count,
    )


@admin_bp.route('/operations', methods=['GET'])
def admin_operations_page():
    """Render an admin-only volunteer/resource optimization dashboard."""
    if not current_user.is_authenticated:
        return redirect(url_for('admin.admin_login_page', next=request.path))
    if current_user.role != 'admin':
        logout_user()
        return redirect(url_for('admin.admin_login_page', next=request.path))

    recommendations = get_operations_snapshot()
    return render_template_string(_ADMIN_OPERATIONS_TEMPLATE, recommendations=recommendations, current_user=current_user)


@admin_bp.route('/operations/data', methods=['GET'])
@requires_min_role('staff')
def admin_operations_data():
    """Return machine-readable operations recommendations for staff/admin users."""
    return jsonify({'recommendations': get_operations_snapshot()}), 200


@admin_bp.route('/users', methods=['GET'])
@requires_min_role('staff')
def list_users():
    """Return all users (staff+ only). Staff can view; only admin can change roles."""
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({'users': [u.to_dict() for u in users]}), 200


@admin_bp.route('/users/<int:user_id>/role', methods=['PATCH'])
@requires_role('admin')
def update_role(user_id):
    """
    Change a user's role. Admin only.
    Expects JSON: { role: 'resident' | 'coordinator' | 'staff' | 'admin' }
    """
    data = request.get_json(silent=True) or {}
    new_role = (data.get('role') or '').strip()

    if not new_role:
        return error_response('VALIDATION_FAILED', 400, {'detail': 'role is required'})

    user, err = update_user_role(user_id, new_role)
    if err:
        status = 404 if err == 'NOT_FOUND' else 400
        return error_response(err, status)

    return jsonify({'message': f'Role updated to {new_role}.', 'user': user.to_dict()}), 200


@admin_bp.route('/users/<int:user_id>/deactivate', methods=['PATCH'])
@requires_role('admin')
def deactivate_user(user_id):
    """Deactivate (soft-delete) a user account. Admin only."""
    from app import db
    user = User.query.get(user_id)
    if not user:
        return error_response('NOT_FOUND', 404)
    user.is_active = False
    db.session.commit()
    return jsonify({'message': 'User deactivated.', 'user': user.to_dict()}), 200
