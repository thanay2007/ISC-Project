"""Create authentication, issuance, analysis and audit tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=32), nullable=True),
    sa.Column('subject', sa.String(length=64), nullable=True),
    sa.Column('network', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('detail', sa.String(length=160), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_actor_id'), 'audit_events', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_events_kind'), 'audit_events', ['kind'], unique=False)
    op.create_index(op.f('ix_audit_events_network'), 'audit_events', ['network'], unique=False)
    op.create_index(op.f('ix_audit_events_subject'), 'audit_events', ['subject'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password', sa.Text(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('signing_key', sa.LargeBinary(), nullable=True),
    sa.Column('public_key', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('certificates',
    sa.Column('ref', sa.String(length=32), nullable=False),
    sa.Column('issuer_id', sa.String(length=32), nullable=False),
    sa.Column('issuer_name', sa.String(length=120), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('signature', sa.String(length=128), nullable=False),
    sa.Column('issued_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('original', sa.LargeBinary(), nullable=False),
    sa.Column('demo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['issuer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('ref')
    )
    op.create_index(op.f('ix_certificates_fingerprint'), 'certificates', ['fingerprint'], unique=False)
    op.create_index(op.f('ix_certificates_issuer_id'), 'certificates', ['issuer_id'], unique=False)
    op.create_table('sessions',
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token')
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('analyses',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('certificate_ref', sa.String(length=32), nullable=True),
    sa.Column('compare_allowed', sa.Boolean(), nullable=False),
    sa.Column('external_ai', sa.Boolean(), nullable=False),
    sa.Column('demo', sa.Boolean(), nullable=False),
    sa.Column('filename', sa.String(length=160), nullable=False),
    sa.Column('mime', sa.String(length=40), nullable=False),
    sa.Column('source', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('stage', sa.String(length=24), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=True),
    sa.Column('report', sa.LargeBinary(), nullable=True),
    sa.Column('progress', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['certificate_ref'], ['certificates.ref'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analyses_owner_id'), 'analyses', ['owner_id'], unique=False)
    op.create_index(op.f('ix_analyses_stage'), 'analyses', ['stage'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_analyses_stage'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_owner_id'), table_name='analyses')
    op.drop_table('analyses')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_certificates_issuer_id'), table_name='certificates')
    op.drop_index(op.f('ix_certificates_fingerprint'), table_name='certificates')
    op.drop_table('certificates')
    op.drop_table('users')
    op.drop_index(op.f('ix_audit_events_subject'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_network'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_kind'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_created_at'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_actor_id'), table_name='audit_events')
    op.drop_table('audit_events')
