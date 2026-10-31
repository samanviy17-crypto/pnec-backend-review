"""Explicit, single-run release operations; no initialization on import."""
import click
from flask import jsonify
from sqlalchemy import text

REVISION = '0001_pnec_release'


def register_release_commands(app):
    @app.cli.command('release-seed')
    @click.option('--approved', is_flag=True, required=True, help='Confirm operator approval and exclusive execution.')
    def release_seed(approved):
        """Seed initial/reference data once AFTER approved migrations."""
        from app import db, _seed_admin_if_missing, _seed_initial_data
        revision = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
        if revision != REVISION:
            raise click.ClickException('Apply the reviewed release migration before seeding.')
        _seed_admin_if_missing(app)
        _seed_initial_data()
        click.echo('Reference data initialized; existing accounts preserved.')

    @app.get('/api/ready')
    def release_ready():
        """Read-only database/schema readiness; do not expose connection errors."""
        from app import db
        try:
            db.session.execute(text('SELECT 1'))
            revision = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
            if revision != REVISION:
                return jsonify({'status': 'not_ready'}), 503
        except Exception:
            db.session.rollback()
            return jsonify({'status': 'not_ready'}), 503
        return jsonify({'status': 'ready', 'schema_revision': REVISION})
