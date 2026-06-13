"""Shared SQLAlchemy engine construction with PgBouncer-safe psycopg settings.

Supabase's transaction-mode connection pooler (PgBouncer) rotates the
underlying server connection per transaction. psycopg creates server-side
prepared statements by default, so a statement prepared on one backend is
missing on the next, surfacing as:

    psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists

Disabling prepared statements (`prepare_threshold=None`) makes psycopg safe
behind a transaction pooler while remaining correct on a direct connection and
in local development. This helper centralises that so every engine in the
project (app, Alembic, readiness checks) uses identical, safe settings.

It only applies the psycopg-specific `connect_args` to `postgresql+psycopg://`
URLs, leaving SQLite/test URLs and other drivers untouched.
"""
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

PSYCOPG_URL_PREFIX = "postgresql+psycopg://"


def psycopg_connect_args(database_url: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return connect_args for the given URL, adding the PgBouncer-safe
    `prepare_threshold=None` for psycopg URLs only. Existing keys are preserved
    (an explicit value is never overwritten)."""
    connect_args: dict[str, Any] = dict(base or {})
    if database_url.startswith(PSYCOPG_URL_PREFIX):
        connect_args.setdefault("prepare_threshold", None)
    return connect_args


def create_app_engine(database_url: str, **kwargs: Any) -> Engine:
    """Create an Engine with project-standard settings:

    - `pool_pre_ping=True` (unless the caller overrides it)
    - psycopg prepared statements disabled for `postgresql+psycopg://` URLs
      (PgBouncer/Supabase transaction-pooler safe)

    Any caller-supplied `connect_args` are preserved and merged. Extra kwargs
    (e.g. `poolclass`) pass straight through to `create_engine`.
    """
    kwargs.setdefault("pool_pre_ping", True)
    connect_args = psycopg_connect_args(database_url, kwargs.pop("connect_args", None))
    return create_engine(database_url, connect_args=connect_args, **kwargs)
