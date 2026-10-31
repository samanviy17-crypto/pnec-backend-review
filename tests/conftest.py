# tests/conftest.py
# Pytest fixtures for Beasts_Flask: app + client + in-memory DB + admin login helper.

import pytest

from app.config import Config


@pytest.fixture
def app(monkeypatch):
    """Create a Flask app with an in-memory SQLite DB.

    The Config class is patched BEFORE create_app() runs because create_app()
    itself calls db.create_all() and seeds initial data (admin user, neighborhoods,
    FAQ, operations, site config) during construction. We must redirect SQLAlchemy
    to :memory: before any of that fires, so we never touch the real instance DB.
    """
    # Patch the URI on the Config class so create_app() picks it up.
    monkeypatch.setattr(Config, 'ADMIN_PASSWORD', 'test-only-admin-password-2026')
    original_uri = Config.SQLALCHEMY_DATABASE_URI
    Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    try:
        # Import here so the patched URI is used during app construction.
        from app import create_app, db as _db

        app = create_app()
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            CSRF_PROTECTION_ENABLED=False,
            SECRET_KEY='test-secret',
        )
        with app.app_context():
            yield app
            _db.session.remove()
            _db.drop_all()
    finally:
        Config.SQLALCHEMY_DATABASE_URI = original_uri


@pytest.fixture
def client(app):
    """Flask test client (anonymous by default)."""
    return app.test_client()


@pytest.fixture
def admin_client(app, client):
    """Test client logged in as the admin seeded by create_app()."""
    from app.models.user import User

    admin = User.query.filter_by(role='admin').first()
    assert admin is not None, "create_app() should have seeded an admin user"
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True
    return client
