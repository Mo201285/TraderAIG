"""Persistence layer: SQLAlchemy engine/session management.

Uses SQLite by default for zero-dependency local development and testing;
switches to PostgreSQL automatically when POSTGRES_* env vars are set.
All business logic goes through repositories, never raw sessions.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_url() -> str:
    host = os.getenv("POSTGRES_HOST")
    if host:
        user = os.getenv("POSTGRES_USER", "traderaig")
        password = os.getenv("POSTGRES_PASSWORD", "")
        name = os.getenv("POSTGRES_DB", "traderaig")
        port = os.getenv("POSTGRES_PORT", "5432")
        return (f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
                f"?connect_timeout=5")

    # SQLite fallback for local dev / tests (kept in project data dir).
    data_dir = Path(__file__).resolve().parent.parent / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'traderaig.db'}"


engine = create_engine(
    _engine_url(),
    poolclass=None if _engine_url().startswith("sqlite") else None,
    connect_args={"check_same_thread": False} if _engine_url().startswith("sqlite") else {},
)

# SQLite in-memory pooling for tests.
_test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables (call once at startup)."""
    ensure_schema()


_schema_ready = False
_schema_lock = threading.Lock()


def _is_sqlite_engine() -> bool:
    return engine.url.get_backend_name() == "sqlite"


def _required_schema() -> dict[str, set[str]]:
    return {
        "experiences": {"metadata_json"},
    }


def _patch_sqlite_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, required_columns in _required_schema().items():
            if not inspector.has_table(table_name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            missing = required_columns - existing
            if table_name == "experiences" and "metadata_json" in missing:
                conn.execute(text("ALTER TABLE experiences ADD COLUMN metadata_json TEXT DEFAULT '{}'"))


def _assert_non_sqlite_schema_compatible() -> None:
    inspector = inspect(engine)
    missing_by_table: dict[str, list[str]] = {}
    for table_name, required_columns in _required_schema().items():
        if not inspector.has_table(table_name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table_name)}
        missing = sorted(required_columns - existing)
        if missing:
            missing_by_table[table_name] = missing
    if missing_by_table:
        raise RuntimeError(
            "Database schema drift detected; explicit migration required: "
            f"{missing_by_table}"
        )


def ensure_schema() -> None:
    """Idempotent create-if-missing for the live engine.

    Guarantees any process using a live session has tables ready, so
    hooks (identity / ledger / adapter) never block or fail on a fresh
    database file.
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        from . import models  # noqa: F401  (register models)

        Base.metadata.create_all(bind=engine)
        if _is_sqlite_engine():
            _patch_sqlite_schema()
        else:
            _assert_non_sqlite_schema_compatible()
        _schema_ready = True


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def session_scope() -> Session:
    """Convenience factory for non-request contexts (workers, CLI)."""
    session = SessionLocal()
    return session


def bind_test_session() -> Session:
    """Return a session bound to an in-memory SQLite DB (for tests)."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=_test_engine)
    s = sessionmaker(bind=_test_engine, autoflush=False, expire_on_commit=False)()
    return s


def make_live_session() -> Session:
    """Return a session bound to the configured engine (SQLite/Postgres)."""
    ensure_schema()
    return SessionLocal()


def persistence_enabled() -> bool:
    """True when the persist-to-DB hook is on (default: on for live runs)."""
    return os.getenv("TRADERAIG_PERSIST", "1") not in ("0", "false", "no")
