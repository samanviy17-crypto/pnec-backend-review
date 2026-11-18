"""Add announcements or adopt an exactly compatible existing table without row changes.

Frozen schema: no application-model imports. Unknown drift/orphans stop for review.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0002_announcements'
down_revision = '0001_pnec_release'
branch_labels = None
depends_on = None


def _columns():
    return [sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('level', sa.String(20), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def _compatible_type(actual, expected):
    if isinstance(expected, sa.Boolean):
        return isinstance(actual, sa.Boolean) or (isinstance(actual, mysql.TINYINT) and actual.display_width == 1)
    if isinstance(expected, sa.Text):
        return isinstance(actual, sa.Text)
    if isinstance(expected, sa.String):
        return isinstance(actual, sa.String) and not isinstance(actual, sa.Text) and actual.length == expected.length
    if isinstance(expected, sa.DateTime):
        return isinstance(actual, sa.DateTime)
    return isinstance(actual, sa.Integer)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'announcements' not in inspector.get_table_names():
        op.create_table('announcements', *_columns())
        return
    actual = {c['name']: c for c in inspector.get_columns('announcements')}
    expected = {c.name: c for c in _columns()}
    if set(actual) != set(expected):
        raise RuntimeError('Announcement schema differs; stop for reviewed reconciliation. No rows changed.')
    for name, column in expected.items():
        if (actual[name]['nullable'] != column.nullable
                or not _compatible_type(actual[name]['type'], column.type)):
            raise RuntimeError('Announcement column differs; stop for reviewed reconciliation. No rows changed.')
    if inspector.get_pk_constraint('announcements')['constrained_columns'] != ['id']:
        raise RuntimeError('Announcement primary key differs; stop for review.')
    keys = inspector.get_foreign_keys('announcements')
    if (len(keys) != 1 or keys[0]['constrained_columns'] != ['created_by']
            or keys[0]['referred_table'] != 'users' or keys[0]['referred_columns'] != ['id']
            or keys[0].get('options')):
        raise RuntimeError('Announcement foreign key differs; stop for review.')
    if inspector.get_unique_constraints('announcements') or any(i.get('unique') for i in inspector.get_indexes('announcements')):
        raise RuntimeError('Unexpected announcement uniqueness constraint; stop for review.')
    orphan = bind.execute(sa.text('SELECT COUNT(*) FROM announcements a LEFT JOIN users u ON a.created_by=u.id WHERE a.created_by IS NOT NULL AND u.id IS NULL')).scalar()
    if orphan:
        raise RuntimeError('Announcement references missing users; stop for reviewed reconciliation.')
    # Compatible legacy table: preserve every value, ID and constraint unchanged.


def downgrade():
    raise RuntimeError('Destructive announcement downgrade is disabled; retain additive schema or restore an approved verified backup.')
