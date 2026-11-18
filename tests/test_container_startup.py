"""Exercise the production admission gate against real migrated disposable databases."""
import importlib.util
from pathlib import Path
import pytest
from tests.test_production_preparation import production

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('container_gate', ROOT/'scripts/check-container-readiness.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.fixture(autouse=True)
def persistent_directories(production):
    Path(production.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)


def test_migrated_production_state_admitted(production):
    production.config['FLASK_PORT'] = 8475
    assert gate.validate_runtime(production)


@pytest.mark.parametrize('key,value', [('DEBUG',True),('AUTO_INITIALIZE_DATABASE',True),('FLASK_PORT',8425),('CSRF_PROTECTION_ENABLED',False),('SESSION_COOKIE_SECURE',False),('SESSION_COOKIE_HTTPONLY',False)])
def test_unsafe_runtime_refused(production,key,value):
    production.config['FLASK_PORT'] = 8475
    production.config[key] = value
    assert not gate.validate_runtime(production)


def test_missing_persistent_directory_refused(production,tmp_path):
    production.config.update(FLASK_PORT=8475,UPLOAD_FOLDER=str(tmp_path/'absent'))
    assert not gate.validate_runtime(production)


def test_missing_sqlite_database_is_not_created(production, tmp_path):
    from app import db

    production.config['FLASK_PORT'] = 8475
    database = tmp_path / 'production-test.db'
    db.engine.dispose()
    database.rename(tmp_path / 'unavailable.db')
    assert not gate.validate_runtime(production)
    assert not database.exists()
