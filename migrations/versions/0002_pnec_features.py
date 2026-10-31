"""Frozen additive announcements/chat baseline; existing schema must match exactly."""
from alembic import op
import sqlalchemy as sa
revision = '0002_pnec_features'
down_revision = '0001_pnec_release'
branch_labels = None
depends_on = None
EXPECTED = {'announcements': {'columns': {'created_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False},
                               'created_by': {'family': 'Integer',
                                              'length': None,
                                              'nullable': True,
                                              'primary_key': False},
                               'expires_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': True,
                                              'primary_key': False},
                               'id': {'family': 'Integer',
                                      'length': None,
                                      'nullable': False,
                                      'primary_key': True},
                               'is_active': {'family': 'Boolean',
                                             'length': None,
                                             'nullable': False,
                                             'primary_key': False},
                               'level': {'family': 'String',
                                         'length': 20,
                                         'nullable': False,
                                         'primary_key': False},
                               'message': {'family': 'String',
                                           'length': None,
                                           'nullable': False,
                                           'primary_key': False},
                               'updated_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False}},
                   'foreign_keys': [(['created_by'], ['users.id'])],
                   'indexes': []},
 'chat_messages': {'columns': {'content': {'family': 'String',
                                           'length': None,
                                           'nullable': False,
                                           'primary_key': False},
                               'created_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False},
                               'id': {'family': 'Integer',
                                      'length': None,
                                      'nullable': False,
                                      'primary_key': True},
                               'image_url': {'family': 'String',
                                             'length': None,
                                             'nullable': True,
                                             'primary_key': False},
                               'role': {'family': 'String',
                                        'length': 20,
                                        'nullable': False,
                                        'primary_key': False},
                               'session_id': {'family': 'Integer',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False}},
                   'foreign_keys': [(['session_id'], ['chat_sessions.id'])],
                   'indexes': [('ix_chat_messages_session_id', ['session_id'], False)]},
 'chat_sessions': {'columns': {'created_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False},
                               'id': {'family': 'Integer',
                                      'length': None,
                                      'nullable': False,
                                      'primary_key': True},
                               'title': {'family': 'String',
                                         'length': 200,
                                         'nullable': True,
                                         'primary_key': False},
                               'updated_at': {'family': 'DateTime',
                                              'length': None,
                                              'nullable': False,
                                              'primary_key': False},
                               'user_id': {'family': 'Integer',
                                           'length': None,
                                           'nullable': False,
                                           'primary_key': False}},
                   'foreign_keys': [(['user_id'], ['users.id'])],
                   'indexes': [('ix_chat_sessions_user_id', ['user_id'], False)]},
 'chat_user_memories': {'columns': {'id': {'family': 'Integer',
                                           'length': None,
                                           'nullable': False,
                                           'primary_key': True},
                                    'memory_json': {'family': 'String',
                                                    'length': None,
                                                    'nullable': False,
                                                    'primary_key': False},
                                    'updated_at': {'family': 'DateTime',
                                                   'length': None,
                                                   'nullable': False,
                                                   'primary_key': False},
                                    'user_id': {'family': 'Integer',
                                                'length': None,
                                                'nullable': False,
                                                'primary_key': False}},
                        'foreign_keys': [(['user_id'], ['users.id'])],
                        'indexes': [('ix_chat_user_memories_user_id', ['user_id'], True)]}}


def upgrade():
    inspector=sa.inspect(op.get_bind())
    existing=set(inspector.get_table_names())
    # Check ALL inherited feature tables before making any changes.
    for name,spec in EXPECTED.items():
        if name not in existing:continue
        columns={c['name']:c for c in inspector.get_columns(name)}
        if set(columns)!=set(spec['columns']):
            raise RuntimeError('Feature schema drift requires review: '+name)
        for key,want in spec['columns'].items():
            got=columns[key]
            if (got['type']._type_affinity.__name__!=want['family'] or
                getattr(got['type'],'length',None)!=want['length'] or
                bool(got['nullable'])!=want['nullable'] or
                bool(got['primary_key'])!=want['primary_key']):
                raise RuntimeError('Feature column drift requires review: '+name+'.'+key)
        actual_indexes={(tuple(sorted(i['column_names'])),bool(i['unique'])) for i in inspector.get_indexes(name)}
        for _,cols,unique in spec['indexes']:
            if (tuple(cols),unique) not in actual_indexes:
                raise RuntimeError('Feature index drift requires review: '+name)
        actual_fks={(tuple(f['constrained_columns']),tuple(f['referred_table']+'.'+c for c in f['referred_columns'])) for f in inspector.get_foreign_keys(name)}
        if any((tuple(cols),tuple(refs)) not in actual_fks for cols,refs in spec['foreign_keys']):
            raise RuntimeError('Feature foreign-key drift requires review: '+name)

    if 'announcements' not in existing:
        op.create_table('announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'chat_sessions' not in existing:
        op.create_table('chat_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)
    if 'chat_user_memories' not in existing:
        op.create_table('chat_user_memories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('memory_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_chat_user_memories_user_id'), 'chat_user_memories', ['user_id'], unique=True)
    if 'chat_messages' not in existing:
        op.create_table('chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_chat_messages_session_id'), 'chat_messages', ['session_id'], unique=False)

def downgrade():
    raise RuntimeError('Destructive downgrade disabled. Use the verified backup/new-target recovery procedure.')
