"""Explicit, single-run release operations; no initialization on import."""
import click
from flask import jsonify
from sqlalchemy import text

REVISION = '0002_pnec_features'


def register_release_commands(app):
    @app.cli.command('release-event-audit')
    def release_event_audit():
        """Read-only timestamp interpretation audit; counts only, no personal data."""
        from app.models.event import Event
        from app.utils.event_time import storage_zone, utc_value
        from werkzeug.exceptions import ServiceUnavailable
        storage_zone()
        invalid = 0
        total = 0
        for row in Event.query.yield_per(500):
            total += 1
            try:
                utc_value(row.date)
            except ServiceUnavailable:
                invalid += 1
        click.echo(f'Events inspected: {total}; ambiguous/nonexistent stored times: {invalid}. No values changed.')
        if invalid:
            raise click.ClickException('Owner review required before deployment; do not guess or bulk-convert legacy data.')

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
            from app.utils.event_time import storage_zone
            storage_zone()
            db.session.execute(text('SELECT 1'))
            revision = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
            from sqlalchemy import inspect
            if revision != REVISION or not set(db.metadata.tables).issubset(set(inspect(db.engine).get_table_names())):
                return jsonify({'status': 'not_ready'}), 503
        except Exception:
            db.session.rollback()
            return jsonify({'status': 'not_ready'}), 503
        return jsonify({'status': 'ready', 'schema_revision': REVISION})
