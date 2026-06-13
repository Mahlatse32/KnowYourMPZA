"""Tests for PgBouncer-safe engine configuration (issue #18).

These tests never open a real DB connection — create_engine is monkeypatched
so we can assert exactly what kwargs/connect_args would be passed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db_engine
from app.db_engine import create_app_engine, psycopg_connect_args

PSYCOPG_URL = "postgresql+psycopg://user:pw@host:5432/db"
SQLITE_URL = "sqlite:///:memory:"
PLAIN_PG_URL = "postgresql://user:pw@host:5432/db"


# ---------------------------------------------------------------------------
# psycopg_connect_args
# ---------------------------------------------------------------------------

def test_psycopg_url_gets_prepare_threshold_none():
    args = psycopg_connect_args(PSYCOPG_URL)
    assert "prepare_threshold" in args
    assert args["prepare_threshold"] is None


def test_non_psycopg_postgres_url_unchanged():
    # Plain postgresql:// (not the +psycopg driver) does not get psycopg-only opts.
    assert psycopg_connect_args(PLAIN_PG_URL) == {}


def test_sqlite_url_gets_no_psycopg_opts():
    assert psycopg_connect_args(SQLITE_URL) == {}
    # explicit sqlite connect_args are preserved untouched
    args = psycopg_connect_args(SQLITE_URL, {"check_same_thread": False})
    assert args == {"check_same_thread": False}


def test_existing_connect_args_preserved_for_psycopg():
    args = psycopg_connect_args(PSYCOPG_URL, {"sslmode": "require"})
    assert args["sslmode"] == "require"
    assert args["prepare_threshold"] is None


def test_explicit_prepare_threshold_not_overwritten():
    args = psycopg_connect_args(PSYCOPG_URL, {"prepare_threshold": 5})
    assert args["prepare_threshold"] == 5  # setdefault never clobbers an explicit value


# ---------------------------------------------------------------------------
# create_app_engine (create_engine monkeypatched — no real connection)
# ---------------------------------------------------------------------------

@pytest.fixture()
def captured(monkeypatch):
    calls = {}

    def fake_create_engine(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return object()  # stand-in engine; never connected

    monkeypatch.setattr(db_engine, "create_engine", fake_create_engine)
    return calls


def test_create_app_engine_psycopg_sets_prepare_threshold_and_pre_ping(captured):
    create_app_engine(PSYCOPG_URL)
    assert captured["url"] == PSYCOPG_URL
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["connect_args"]["prepare_threshold"] is None


def test_create_app_engine_sqlite_no_psycopg_opts(captured):
    create_app_engine(SQLITE_URL)
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["connect_args"] == {}


def test_create_app_engine_preserves_caller_connect_args(captured):
    create_app_engine(PSYCOPG_URL, connect_args={"sslmode": "require"})
    ca = captured["kwargs"]["connect_args"]
    assert ca["sslmode"] == "require"
    assert ca["prepare_threshold"] is None


def test_create_app_engine_passes_through_poolclass(captured):
    from sqlalchemy import pool

    create_app_engine(PSYCOPG_URL, poolclass=pool.NullPool)
    assert captured["kwargs"]["poolclass"] is pool.NullPool
    assert captured["kwargs"]["connect_args"]["prepare_threshold"] is None


def test_create_app_engine_pool_pre_ping_overridable(captured):
    create_app_engine(PSYCOPG_URL, pool_pre_ping=False)
    assert captured["kwargs"]["pool_pre_ping"] is False


# ---------------------------------------------------------------------------
# Call sites use the shared helper
# ---------------------------------------------------------------------------

def test_app_db_uses_shared_helper():
    src = (Path(__file__).resolve().parents[1] / "app" / "db.py").read_text(encoding="utf-8")
    assert "create_app_engine" in src
    assert "create_engine(settings.database_url" not in src  # no raw engine left


def test_alembic_env_uses_shared_helper():
    src = (Path(__file__).resolve().parents[1] / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "create_app_engine" in src


def test_readiness_uses_shared_helper():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "check_persistent_db_ready.py").read_text(encoding="utf-8")
    assert "create_app_engine" in src
    assert "create_engine(database_url, pool_pre_ping=True)" not in src


# ---------------------------------------------------------------------------
# No secrets leaked
# ---------------------------------------------------------------------------

def test_helper_source_has_no_hardcoded_credentials():
    src = (Path(__file__).resolve().parents[1] / "app" / "db_engine.py").read_text(encoding="utf-8")
    assert "password" not in src.lower() or "DATABASE_URL" not in src  # no secret value embedded
    assert "://" not in src.replace("postgresql+psycopg://", "")  # only the scheme prefix constant
