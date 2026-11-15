import pytest

from backend.verifex.db import normalize_database_url


def test_supabase_dashboard_url_uses_psycopg_and_tls():
    url = normalize_database_url(
        "postgresql://postgres.example:p%40ss%2Fword@aws-0-example.pooler.supabase.com:5432/postgres"
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "postgres.example"
    assert url.password == "p@ss/word"
    assert url.query["sslmode"] == "require"
    assert url.query["connect_timeout"] == "10"


def test_supabase_preserves_explicit_certificate_verification():
    url = normalize_database_url(
        "postgresql://postgres:example@db.project.supabase.co:5432/postgres?sslmode=verify-full&sslrootcert=root.crt"
    )
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == "root.crt"


@pytest.mark.parametrize(("value", "message"), [
    ("", "Set DATABASE_URL"),
    ("postgresql://postgres:example@aws-0-example.pooler.supabase.com:6543/postgres", "port 5432"),
    ("postgresql://postgres:example@db.project.supabase.co/postgres?sslmode=disable", "sslmode=require"),
])
def test_database_config_rejects_unsupported_supabase_settings(value, message):
    with pytest.raises(ValueError, match=message):
        normalize_database_url(value)
