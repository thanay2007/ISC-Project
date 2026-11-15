from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError


def upgrade(engine):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations").replace("%", "%%"))
    try:
        connection = engine.connect()
    except OperationalError as error:
        if engine.dialect.name != "postgresql":
            raise
        raise RuntimeError(
            "Could not connect to PostgreSQL. Check DATABASE_URL in .env, DNS, and network access. "
            "For Supabase, copy the Session pooler URL from the project dashboard. "
            "For local SQLite, run .\\run.ps1 -LocalDatabase or bash ./run.sh --local-database. "
            "See documentation/SETUP.md for troubleshooting."
        ) from error

    with connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
