"""Keep VERIFEX tables accessible through the backend's database role."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = ("users", "sessions", "certificates", "analyses", "audit_events", "alembic_version")


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    api_roles = connection.execute(sa.text(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')"
    )).scalars().all()
    grantees = ", ".join(["PUBLIC", *api_roles])
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {grantees}")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
