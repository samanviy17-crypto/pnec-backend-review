# app/config.py
# Responsibility: All Flask configuration in one place.
# Environment variables override defaults for production deployments.

import os
from urllib.parse import urlsplit
from sqlalchemy.engine import URL, make_url
from datetime import timedelta
from dotenv import load_dotenv

# Review snapshots must not discover credentials from ancestor directories.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))


class Config:
    """Base configuration shared by all environments."""

    # ─── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    SESSION_COOKIE_NAME = 'pnec_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    JWT_TOKEN_NAME = 'pnec_jwt'
    BEARER_TOKEN_MAX_AGE = 86400
    CSRF_PROTECTION_ENABLED = True
    RATE_LIMIT_STORAGE = 'memory'
    AUTO_INITIALIZE_DATABASE = True
    SECURITY_STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'volumes', 'security-limits.json')

    # ─── Database ─────────────────────────────────────────────────────────────
    DB_ENDPOINT = os.environ.get('DB_ENDPOINT') or None
    DB_USERNAME = os.environ.get('DB_USERNAME') or None
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or None

    @staticmethod
    def build_db_uri():
        ep = os.environ.get('DB_ENDPOINT')
        un = os.environ.get('DB_USERNAME')
        pw = os.environ.get('DB_PASSWORD')
        if ep and un and pw:
            return f'mysql+pymysql://{un}:{pw}@{ep}:3306/pnec'
        # Absolute path so Flask works regardless of CWD
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base, 'instance', 'volumes', 'pnec.db')
        return f'sqlite:///{db_path}'

    SQLALCHEMY_DATABASE_URI = build_db_uri.__func__()
    SQLALCHEMY_BACKUP_URI = 'sqlite:///volumes/pnec_bak.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ─── File uploads ─────────────────────────────────────────────────────────
    # Bumped 10→20 MB to match the upload-page UI ("Max 20MB"). Was a
    # silent-413 footgun: coordinators uploading event photos from a
    # phone hit a baffling failure with no actionable error UI.
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB
    UPLOAD_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4']
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'instance', 'uploads')

    # ─── Admin seed credentials ────────────────────────────────────────────────
    # SECURITY: ADMIN_PASSWORD MUST be set via env. The previous fallback
    # ('changeme123') seeded a known admin account on every fresh deploy
    # — anyone who'd read the public repo could log into prod as admin.
    # Now: if ADMIN_PASSWORD is unset OR equals a known-bad sentinel, the
    # _seed_admin_if_missing() boot step refuses to create an admin and
    # logs a loud warning instead.
    PUBLIC_CONTACT_EMAIL = os.environ.get('PUBLIC_CONTACT_EMAIL') or None
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL') or 'contact@example.test'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')   # NO fallback — see __init__.py:_seed_admin_if_missing
    ADMIN_DISPLAY_NAME = os.environ.get('ADMIN_DISPLAY_NAME') or 'PNEC Admin'

    # ─── Email (Flask-Mail) ────────────────────────────────────────────────────
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or None
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_DELIVERY = os.environ.get('MAIL_DELIVERY', 'auto')
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:4500').rstrip('/')
    PASSWORD_RESET_MAX_AGE = 86400
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or None
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or None
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'contact@example.test'

    # ─── External APIs ────────────────────────────────────────────────────────
    OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
    POWAY_LAT = 32.9628
    POWAY_LON = -117.0359
    RISK_CACHE_SECONDS = 1800  # 30 minutes
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or None
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL') or 'gemini-2.5-flash-lite'
    GEMINI_API_URL = os.environ.get('GEMINI_API_URL') or 'https://generativelanguage.googleapis.com/v1beta'
    GEMINI_RATE_LIMIT_PER_MINUTE = int(os.environ.get('GEMINI_RATE_LIMIT_PER_MINUTE') or 20)
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY') or None
    GROQ_MODEL = os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile'
    GROQ_API_URL = 'https://api.groq.com/openai/v1'
    REDIS_URL = os.environ.get('REDIS_URL') or None

    # ─── Web Push (VAPID) ─────────────────────────────────────────────────────
    VAPID_PUBLIC_KEY  = os.environ.get('VAPID_PUBLIC_KEY', '')
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
    VAPID_EMAIL       = os.environ.get('VAPID_EMAIL', 'contact@example.test')

    # ─── CMS v2 ───────────────────────────────────────────────────────────────
    # Where on disk the section type definitions live (each subdir is a type
    # containing <type>.html and <type>.schema.json).
    CMS_SECTIONS_PATH = os.environ.get('CMS_SECTIONS_PATH') or os.path.join(
        os.path.dirname(__file__), 'cms_sections'
    )

    # ─── GitHub publish (v3.15) ──────────────────────────────────────────────
    # When the Live Theme Editor's "Publish to GitHub" button is clicked,
    # the backend commits the changed source files to the public repo via
    # the GitHub REST API. Pages then rebuilds the deploy in ~5 min.
    #
    # GITHUB_TOKEN: a fine-grained PAT with "Contents: read+write" on the
    #               two PNEC repos. NEVER commit this to source — only set
    #               via env var on the production host.
    GITHUB_PUBLISH_ENABLED = os.environ.get('GITHUB_PUBLISH_ENABLED', 'false').lower() == 'true'
    GITHUB_TOKEN  = os.environ.get('GITHUB_TOKEN') or None
    GITHUB_OWNER  = os.environ.get('GITHUB_OWNER')  or ''
    GITHUB_REPO   = os.environ.get('GITHUB_REPO')   or ''
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH') or 'review-only'


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    RATE_LIMIT_STORAGE = 'file'
    AUTO_INITIALIZE_DATABASE = False


config_map = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'default':     DevelopmentConfig,
}


def get_config():
    """Return the correct Config class based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env not in config_map:
        raise RuntimeError('Invalid FLASK_ENV; choose development or production.')
    return config_map[env]


def configure_production(config):
    """Validate deployment inputs before opening databases. Never log values."""
    secret = os.environ.get('SECRET_KEY', '')
    lowered = secret.lower()
    if (not 32 <= len(secret) <= 512 or len(set(secret)) < 12 or
            any(word in lowered for word in ('secret', 'change-in-prod', 'changeme', 'development', 'example', 'password', 'replace', 'default'))):
        raise RuntimeError('Production SECRET_KEY must be a strong, independently generated secret of at least 32 characters.')
    if any(len(secret) % size == 0 and secret == secret[:size] * (len(secret) // size)
           for size in range(1, len(secret) // 2 + 1)):
        raise RuntimeError('Production SECRET_KEY must not be a repeated pattern.')
    config['SECRET_KEY'] = secret
    frontend = os.environ.get('FRONTEND_URL', '')
    try:
        parsed = urlsplit(frontend)
        port = parsed.port
    except ValueError:
        raise RuntimeError('Production FRONTEND_URL is invalid.') from None
    approved_frontends = set(os.environ.get('ALLOWED_FRONTEND_ORIGINS', 'https://pnec.opencodingsociety.com,https://pnec-review.invalid').split(','))
    approved_frontends = {origin.strip().rstrip('/') for origin in approved_frontends if origin.strip()}
    if (parsed.scheme != 'https' or frontend.rstrip('/') not in approved_frontends
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise RuntimeError('Production FRONTEND_URL must be the approved HTTPS PNEC root origin.')
    config['FRONTEND_URL'] = frontend.rstrip('/')
    config['APPROVED_ORIGINS'] = [config['FRONTEND_URL']]
    config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER') or config.get('UPLOAD_FOLDER', '')
    if config['UPLOAD_FOLDER'] and not os.path.isabs(config['UPLOAD_FOLDER']):
        raise RuntimeError('UPLOAD_FOLDER must be an absolute persistent path.')
    parts = [os.environ.get(name) for name in ('DB_ENDPOINT', 'DB_USERNAME', 'DB_PASSWORD')]
    explicit = os.environ.get('DATABASE_URL')
    if any(parts) and not all(parts):
        raise RuntimeError('Production database configuration is incomplete.')
    if explicit and any(parts):
        raise RuntimeError('Choose DATABASE_URL or DB_ENDPOINT/DB_USERNAME/DB_PASSWORD, not both.')
    if explicit:
        try:
            url = make_url(explicit)
            valid = (url.drivername == 'sqlite' and url.database and os.path.isabs(url.database)
                     and url.database != ':memory:') or (url.drivername == 'mysql+pymysql'
                     and url.host and url.username and url.password and url.database)
        except Exception:
            valid = False
        if not valid:
            raise RuntimeError('Production DATABASE_URL must explicitly select persistent SQLite or MySQL.')
        config['SQLALCHEMY_DATABASE_URI'] = url
    elif all(parts):
        config['SQLALCHEMY_DATABASE_URI'] = URL.create('mysql+pymysql', username=parts[1], password=parts[2], host=parts[0], port=3306, database='pnec')
    else:
        raise RuntimeError('Production requires an explicit database configuration; no SQLite fallback is allowed.')
    try:
        ttl = int(os.environ.get('BEARER_TOKEN_MAX_AGE', '86400'))
        if not 60 <= ttl <= 2592000:
            raise ValueError
    except ValueError:
        raise RuntimeError('BEARER_TOKEN_MAX_AGE must be 60–2592000 seconds.') from None
    config['BEARER_TOKEN_MAX_AGE'] = ttl
    config['SECURITY_STATE_PATH'] = os.environ.get('SECURITY_STATE_PATH') or config['SECURITY_STATE_PATH']
    if not os.path.isabs(config['SECURITY_STATE_PATH']):
        raise RuntimeError('SECURITY_STATE_PATH must be an absolute path on a shared local persistent volume.')
