"""Associate VERIFEX accounts with Clerk users."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("clerk_subject", sa.String(255), nullable=True))
    op.create_index("ix_users_clerk_subject", "users", ["clerk_subject"], unique=True)


def downgrade():
    op.drop_index("ix_users_clerk_subject", table_name="users")
    op.drop_column("users", "clerk_subject")
