"""Store encrypted issuer metadata and in-progress evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("certificates", sa.Column("private_metadata", sa.LargeBinary(), nullable=True))
    op.add_column("analyses", sa.Column("partial", sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column("analyses", "partial")
    op.drop_column("certificates", "private_metadata")
