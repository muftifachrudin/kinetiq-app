"""Shared DATABASE_URL handling for every service that connects to Postgres.

Neon's GitHub Action and Railway both hand out bare "postgresql://" URLs,
which makes SQLAlchemy default to the psycopg2 dialect -- this project
depends on psycopg (v3) instead. See docs/deployment-runbook.md.
"""

from sqlalchemy.engine import URL, make_url


def normalize_db_url(raw_url: str) -> str:
    """Force the postgresql+psycopg drivername, whatever scheme is passed in."""
    url: URL = make_url(raw_url).set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)
