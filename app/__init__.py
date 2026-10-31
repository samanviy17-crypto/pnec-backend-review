# app/__init__.py
# Responsibility: Flask application factory — creates and wires together the app instance.
# All extensions, blueprints, and startup tasks are registered here and nowhere else.

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_cors import CORS
from sqlalchemy import inspect, text

try:
    from flask_mail import Mail
    mail = Mail()
    MAIL_ENABLED = True
except ImportError:
    mail = None
    MAIL_ENABLED = False
    print("Warning: flask_mail not installed. Email notifications disabled.")

# ─── Extension instances (no app bound yet) ───────────────────────────────────
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()


def create_app(initialize_database=None):
    """
    Purpose: Bootstrap the Flask application with all extensions and blueprints.
    @returns {Flask} Fully configured Flask application instance
    Algorithm:
    1. Instantiate Flask app
    2. Load configuration
    3. Initialize extensions
    4. Register all route blueprints
    5. Create database tables and seed admin on first run
    """
    app = Flask(__name__, instance_relative_config=False)

    # ── Load configuration ────────────────────────────────────────────────────
    from app.config import get_config, configure_production
    config_class = get_config()
    app.config.from_object(config_class)
    from app.config import ProductionConfig
    if config_class is ProductionConfig:
        configure_production(app.config)

    # ── Initialize extensions ─────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    if MAIL_ENABLED:
        mail.init_app(app)

    @app.before_request
    def _reset_request_identity():
        # Also prevents identity leakage when an embedding/test application
        # deliberately reuses an application context across HTTP requests.
        from flask import g
        g.pop('_login_user', None)

    from app.utils.csrf import APPROVED_ORIGINS, install_csrf_protection
    if config_class is not ProductionConfig:
        app.config['APPROVED_ORIGINS'] = APPROVED_ORIGINS
    install_csrf_protection(app)

    CORS(
        app,
        supports_credentials=True,
        origins=app.config['APPROVED_ORIGINS'],
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        allow_headers=[
            'Authorization', 'Origin', 'X-Origin', 'X-Requested-With',
            'Content-Type', 'Accept', 'X-CSRF-Token',
        ],
    )

    @app.get('/')
    def root_health():
        """PNEC service discovery; no unrelated classroom landing page."""
        return jsonify({'service':'PNEC API','health':'/api/health','readiness':'/api/ready'})

    @app.get('/api/health')
    def api_health():
        """Return a simple machine-readable health payload."""
        return jsonify({'status': 'ok', 'message': 'Flask backend is running', 'port': app.config.get('FLASK_PORT', 8425)}), 200

    # ── Bearer token → Flask-Login session bridge ─────────────────────────────
    @app.before_request
    def _load_user_from_bearer():
        """Use the supplied bearer identity consistently with authenticated API helpers."""
        if request.headers.get('Authorization', '').startswith('Bearer '):
            from app.utils.auth_helpers import get_token_user
            token_user = get_token_user()
            # Request-local identity only: a bearer must not mint a longer-lived
            # cookie session, and an invalid bearer must not fall back to one.
            login_manager._update_request_context_with_user(
                token_user if token_user is not None else login_manager.anonymous_user())

    # ── Register blueprints ───────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Initialize CMS v2 section-type registry ──────────────────────────────
    from app.services.cms_registry import CmsRegistry
    registry = CmsRegistry(app.config.get('CMS_SECTIONS_PATH', ''))
    registry.load()
    app.config['CMS_REGISTRY'] = registry

    # ── Security hardening: HTTP response headers + cookie hardening ─────────
    # Adds X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
    # Permissions-Policy, Content-Security-Policy, Strict-Transport-Security
    # to every API response. Addresses OWASP A02 (Security Misconfiguration).
    from app.utils.security import install_security_headers
    install_security_headers(app)
    # Eager-import the SecurityEvent model so db.create_all picks it up
    from app.models import security_event  # noqa: F401
    # v3.14 — same for volunteer interest submissions
    from app.models import volunteer_interest  # noqa: F401

    # ── Cookie security defaults — applied site-wide regardless of env ───────
    app.config.setdefault('SESSION_COOKIE_SECURE',   not app.config.get('DEBUG', False))
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    app.config.setdefault('REMEMBER_COOKIE_SECURE', not app.config.get('DEBUG', False))
    app.config.setdefault('REMEMBER_COOKIE_HTTPONLY', True)
    app.config.setdefault('REMEMBER_COOKIE_SAMESITE', 'Lax')

    # Production workers never create/alter/seed schema. Explicit CLI jobs
    # migrate and seed once before workers are admitted to traffic.
    if initialize_database is None:
        initialize_database = app.config['AUTO_INITIALIZE_DATABASE']
    if initialize_database and config_class is ProductionConfig:
        raise RuntimeError('Production initialization must use the reviewed migration/seed CLI procedure.')
    if initialize_database:
        with app.app_context():
            db.create_all()
            _sync_legacy_sqlite_schema()
            _seed_admin_if_missing(app)
            _seed_initial_data()

    from app.release import register_release_commands
    register_release_commands(app)

    return app


def _register_blueprints(app):
    """
    Purpose: Import and register every route blueprint onto the app.
    @param {Flask} app - The Flask application instance
    Algorithm:
    1. Import each blueprint module
    2. Register with url_prefix
    """
    from app.routes.preparedness import preparedness_bp
    app.register_blueprint(preparedness_bp, url_prefix="/api")
    from app.routes.announcement import announcements_bp
    app.register_blueprint(announcements_bp, url_prefix='/api')
    from app.routes.chat import chat_bp
    app.register_blueprint(chat_bp, url_prefix='/api')
    from app.routes.auth import auth_bp
    from app.routes.legacy_user import legacy_user_bp
    from app.routes.faq import faq_bp
    from app.routes.neighborhoods import neighborhoods_bp
    from app.routes.risk import risk_bp
    from app.routes.events import events_bp
    from app.routes.media import media_bp
    # v3.16: game + escape_room blueprints removed — those features
    # were retired (not user-facing on the production site).
    from app.routes.admin import admin_bp
    from app.routes.gemini import gemini_bp
    from app.routes.news import news_bp
    from app.routes.blog import blog_bp
    # cms_manifest_bp removed in Phase 4 cleanup — only the retired v1
    # editor consumed /api/cms/manifest/<slug>, so the route file +
    # blueprint registration are gone.
    from app.routes.cms_v2 import cms_v2_bp
    from app.routes.cms_theme import cms_theme_bp
    from app.routes.cms_ai import cms_ai_bp
    from app.routes.site_config import site_config_bp
    from app.routes.page_overrides import page_overrides_bp
    from app.routes.security import security_bp
    from app.routes.live import live_bp
    from app.routes.volunteer import volunteer_bp
    from app.routes.admin_publish import admin_publish_bp

    app.register_blueprint(auth_bp,          url_prefix='/api/auth')
    app.register_blueprint(legacy_user_bp,   url_prefix='/api')
    app.register_blueprint(faq_bp,           url_prefix='/api')
    app.register_blueprint(neighborhoods_bp, url_prefix='/api')
    app.register_blueprint(risk_bp,          url_prefix='/api')
    app.register_blueprint(events_bp,        url_prefix='/api')
    app.register_blueprint(media_bp,         url_prefix='/api')
    from app.routes.media import serve_upload
    app.add_url_rule('/static/uploads/<path:filename>', 'serve_upload', serve_upload)
    app.register_blueprint(admin_bp,         url_prefix='/api/admin')
    app.register_blueprint(gemini_bp,        url_prefix='/api')
    app.register_blueprint(news_bp,          url_prefix='/api')
    app.register_blueprint(blog_bp,          url_prefix='/api')
    app.register_blueprint(cms_v2_bp,         url_prefix='/api')
    app.register_blueprint(cms_theme_bp,      url_prefix='/api')
    app.register_blueprint(cms_ai_bp,         url_prefix='/api')
    # v1 CMS — site-config (cross-page values) + page-overrides (per-page text).
    # Both feed hydrate.js's data-cms-config / data-cms-override swap.
    app.register_blueprint(site_config_bp,    url_prefix='/api')
    app.register_blueprint(page_overrides_bp, url_prefix='/api')
    app.register_blueprint(security_bp,       url_prefix='/api')
    # v3.8 — chatbot's "right now" aggregator (weather + AQI + NWS alerts +
    # fire-weather composite + sun). Read-only, public. Caches upstream
    # for 30 min so a busy chat day costs at most 48 fetches each.
    app.register_blueprint(live_bp,           url_prefix='/api')
    # v3.14 — volunteer interest submissions + admin management
    app.register_blueprint(volunteer_bp,      url_prefix='/api')
    # v3.15 — Live Theme Editor's publish-to-GitHub + Groq AI endpoints
    app.register_blueprint(admin_publish_bp,  url_prefix='/api')


def _seed_admin_if_missing(app):
    """
    Purpose: Create the admin user on first run if no admin exists.
    @param {Flask} app - App instance (used for config access)
    Algorithm:
    1. Query for any existing admin user
    2. If none found, create from env-configured credentials
    3. Commit to database
    """
    from app.models.user import User
    from werkzeug.security import generate_password_hash

    existing_admin = User.query.filter_by(role='admin').first()
    if existing_admin:
        return

    # SECURITY: refuse to seed an admin without an explicit env-supplied
    # password. The previous fallback ('changeme123') seeded a known
    # account on every fresh deploy. Sentinel values are also rejected.
    pw = app.config.get('ADMIN_PASSWORD')
    BAD_SENTINELS = {None, '', 'changeme', 'changeme123', 'password', 'admin', 'admin123'}
    if pw in BAD_SENTINELS or (isinstance(pw, str) and len(pw) < 12):
        try:
            app.logger.warning(
                '_seed_admin_if_missing: refusing to seed admin — '
                'set ADMIN_PASSWORD env var to a strong (>=12 char) secret. '
                'No admin will exist until this is provided.'
            )
        except Exception:
            pass
        return

    admin = User(
        email=app.config['ADMIN_EMAIL'],
        password_hash=generate_password_hash(pw, method='pbkdf2:sha256'),
        display_name=app.config['ADMIN_DISPLAY_NAME'],
        role='admin',
        is_active=True,
    )
    db.session.add(admin)
    db.session.commit()


def _sync_legacy_sqlite_schema():
    """
    Purpose: Patch older local SQLite schemas so current models can query safely.
    Algorithm:
    1. Skip non-SQLite databases
    2. Inspect the existing users table
    3. Add missing columns introduced after the table was first created
    """
    engine = db.engine
    if engine.dialect.name != 'sqlite':
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if 'users' not in tables:
        return

    existing_columns = {col['name'] for col in inspector.get_columns('users')}
    missing_columns = [
        ('bio', 'ALTER TABLE users ADD COLUMN bio TEXT'),
        ('avatar_url', 'ALTER TABLE users ADD COLUMN avatar_url TEXT'),
        ('phone', 'ALTER TABLE users ADD COLUMN phone VARCHAR(20)'),
        ('auth_token', 'ALTER TABLE users ADD COLUMN auth_token VARCHAR(64)'),
    ]

    for column_name, ddl in missing_columns:
        if column_name not in existing_columns:
            db.session.execute(text(ddl))

    db.session.commit()


def _seed_initial_data():
    """
    Purpose: Seed neighborhoods and FAQ data on first run.
    @returns {void}
    Algorithm:
    1. Call seed_neighborhoods() — skips if data exists
    2. Call seed_faq() — skips if data exists
    """
    from app.services.neighborhood_service import seed_neighborhoods
    from app.services.faq_service import seed_faq
    from app.services.operations_service import seed_operations_data
    seed_neighborhoods()
    seed_faq()
    seed_operations_data()


# ── Flask-Login: return JSON 401 instead of HTML redirect ─────────────────────
@login_manager.unauthorized_handler
def unauthorized():
    from flask import jsonify
    return jsonify({'error': 'UNAUTHORIZED', 'message': 'Login required.'}), 401


# ── Flask-Login user loader ────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    """
    Purpose: Reload a user object from the database by user ID for Flask-Login.
    @param {str} user_id - The user's primary key as a string
    @returns {User|None} The User instance or None
    """
    from app.models.user import User
    import secrets
    try:
        parts = user_id.split(':', 1)
        user = db.session.get(User, int(parts[0]))
    except (TypeError, ValueError):
        return None
    if not user or not user.is_active:
        return None
    if len(parts) == 1:
        # Legacy users without bearer credentials can keep their old sessions.
        return user if user.auth_token is None else None
    stamp = user.get_id().split(':', 1)[1]
    return user if secrets.compare_digest(parts[1], stamp) else None
