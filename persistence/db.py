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

    # An explicit SQLite file, if one was named.
    #
    # Honoured *before* the `.data` default rather than after it, because the
    # default is the live backend's own database on this host. A knob that is
    # set but ignored is worse than an absent one: a test harness that sets
    # `TRADERAIG_DB_PATH` to a temp file and is silently ignored will write its
    # rows into the running system's tables, and every assertion it makes about
    # isolation is measuring nothing.
    explicit = os.getenv("TRADERAIG_DB_PATH")
    if explicit:
        path = Path(explicit)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"

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


def _required_schema() -> dict[str, dict[str, str]]:
    """Columns this build needs that an older database may lack, and the DDL
    type to add them as.

    Was a `set[str]` with one hard-coded `ALTER` for `experiences`; it is now
    column -> type so adding a column is one line instead of a special case.
    `experiences.metadata_json` keeps its original default, because a data
    migration and a schema migration are different jobs.
    """
    return {
        "experiences": {"metadata_json": "TEXT DEFAULT '{}'", "owner_user_id": "TEXT"},
        "users": {"password_hash": "TEXT", "password_set_at": "FLOAT"},
        # The trailing high-water mark. Nullable so the ALTER is additive and no
        # existing row is rewritten: a row written before trailing existed has
        # no peak, and inventing one here would be a fabricated limit wearing a
        # column name.
        "challenge_baselines": {"equity_peak": "FLOAT"},
        # Account-scoped audit trail. Nullable and additive so existing rows are
        # untouched; a row written before accounts existed has no account to name,
        # and inventing one from `object_type` would attribute a historical
        # decision to a login it never touched.
        "audit": {"account_id": "TEXT"},
        # Partner attribution (S9 ecosystem). Additive and nullable: evidence or
        # a source written before partners existed has no partner to name, and
        # inventing one would attribute external matter to a provider that never
        # supplied it -- an unattributed row stays unattributed.
        "source_registry": {"partner_id": "TEXT"},
        "evidence_items": {"partner_id": "TEXT"},
        # The referral reward contract: the commercial product a referral
        # program pays out in, added to the ExternalProviderRecord model
        # without a migration entry, so databases created before it existed
        # never gained the column on their old external_providers table (a
        # fresh CREATE still has it). Additive and nullable; a provider
        # registered before the contract existed has no product to name, and
        # inventing one would fabricate a commercial term.
        "external_providers": {"referral_reward_product": "TEXT"},
    }


def _patch_sqlite_schema() -> None:
    """Additive, non-destructive: SQLite cannot ADD COLUMN with a NOT NULL
    constraint or a default that backfills a non-constant, and every column
    added here is nullable, so no data is rewritten and no row is lost."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, required_columns in _required_schema().items():
            if not inspector.has_table(table_name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            for column, ddl_type in required_columns.items():
                if column in existing:
                    continue
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {column} {ddl_type}"))
                print(f"schema: added {table_name}.{column}")


def _assert_non_sqlite_schema_compatible() -> None:
    inspector = inspect(engine)
    missing_by_table: dict[str, list[str]] = {}
    for table_name, required_columns in _required_schema().items():
        if not inspector.has_table(table_name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table_name)}
        missing = sorted(set(required_columns) - existing)
        if missing:
            missing_by_table[table_name] = missing
    if missing_by_table:
        raise RuntimeError(
            "Database schema drift detected; explicit migration required: "
            f"{missing_by_table}"
        )


def _register_models() -> None:
    """Import every model module so `Base.metadata` knows about its tables.

    `create_all` only creates tables whose classes have been imported, so a model
    module that nobody imports at startup is a table that does not exist in the
    live database while every repository still queries it -- a repository that
    raises `no such table` on first call and looks like a wiring bug rather than
    a missing registration.

    Account and trade models live in their own modules rather than in `models.py`
    so this list is the single place that says which schema modules exist.
    """
    from . import models  # noqa: F401  (register models)
    from . import models_accounts  # noqa: F401  (register models)
    from . import models_events  # noqa: F401  (register models)
    from . import models_trades  # noqa: F401  (register models)


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
        _register_models()

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
    _register_models()

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
