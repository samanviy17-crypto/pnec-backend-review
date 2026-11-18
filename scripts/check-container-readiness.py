"""Read-only production container startup gate; never migrates or seeds."""
import os
from pathlib import Path


def validate_runtime(app):
    from app import db

    config = app.config
    if (config.get('DEBUG') or config.get('AUTO_INITIALIZE_DATABASE')
            or config.get('FLASK_PORT') != 8630
            or not config.get('CSRF_PROTECTION_ENABLED')
            or not config.get('SESSION_COOKIE_SECURE')
            or not config.get('SESSION_COOKIE_HTTPONLY')):
        return False
    upload = Path(config['UPLOAD_FOLDER'])
    limits = Path(config['SECURITY_STATE_PATH']).parent
    if not all(path.is_dir() and os.access(path, os.W_OK) for path in (upload, limits)):
        return False
    with app.app_context():
        database = db.engine.url
        if database.get_backend_name() == 'sqlite' and not Path(database.database).is_file():
            return False
    response = app.test_client().get('/api/ready')
    return response.status_code == 200 and response.json.get('status') == 'ready'


def main():
    from main import app
    if not validate_runtime(app):
        print('Container not admitted: verify production policy, persistent directory permissions and separately approved migrations. No automatic repair performed.')
        return 1
    print('Production startup policy, writable state directories and schema readiness verified.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
