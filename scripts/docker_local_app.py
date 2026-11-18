"""Explicitly disposable production-policy bootstrap. Never use on the server."""
import os
import secrets
from pathlib import Path


def create_disposable_app(state_dir='/var/lib/pnec'):
    if os.environ.get('PNEC_DOCKER_DISPOSABLE_TEST') != 'true':
        raise RuntimeError('Disposable local marker required')
    if any(os.environ.get(key) for key in ('DATABASE_URL', 'DB_ENDPOINT', 'DB_USERNAME', 'DB_PASSWORD', 'SECRET_KEY')):
        raise RuntimeError('Refusing inherited database or secret configuration')
    state = Path(state_dir).resolve()
    database = state / 'disposable.sqlite3'
    state.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental reuse or resetting existing data.
    with database.open('x'):
        pass
    os.environ.update(
        FLASK_ENV='production', FLASK_PORT='8475',
        FRONTEND_URL='https://powaynec.opencodingsociety.com',
        SECRET_KEY=secrets.token_urlsafe(48),
        DATABASE_URL='sqlite:///' + str(database),
        SECURITY_STATE_PATH=str(state / 'limits.json'),
        UPLOAD_FOLDER=str(state / 'uploads'),
        MAIL_DELIVERY='disabled', PNEC_REVIEW_EPHEMERAL='false',
    )
    (state / 'uploads').mkdir(mode=0o700)
    import requests
    def blocked(*args, **kwargs):
        raise requests.ConnectionError('External providers disabled in disposable Docker test')
    requests.sessions.Session.request = blocked
    from app import create_app
    from flask_migrate import upgrade
    app = create_app(initialize_database=False)
    with app.app_context():
        upgrade(directory=str(Path(__file__).resolve().parents[1] / 'migrations'))
    return app


# Gunicorn imports this name; tests can import the factory under a different name.
if __name__ == 'scripts.docker_local_app':
    app = create_disposable_app()
