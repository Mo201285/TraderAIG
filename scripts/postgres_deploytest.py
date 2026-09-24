"""PostgreSQL production deployment verification (against a live server).

Proves the whole persistence surface on a real PostgreSQL server: schema
bootstrap, canonical tables, a real session round-trip, and (by default) the
full pytest suite with the engine bound to PostgreSQL.

Lifecycle is deliberately OUT of this script: the running server is owned by
the caller (``scripts/postgres_prod_test.ps1`` launches it detached via WMI —
starting a server from inside the terminal harness made every spawned backend
crash with STATUS_DLL_INIT_FAILED, because ``postgres`` inherited console
handles from a killed launcher; WMI-launched servers run cleanly).

Env contract matches ``persistence/db.py::_engine_url``: when ``POSTGRES_HOST``
is set, SQLAlchemy connects to PostgreSQL.

Usage::

    python scripts/postgres_deploytest.py [--no-suite] [--port 5432]
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

import sqlalchemy as sa


def _connect(host: str, port: int, user: str, password: str, db: str) -> sa.Engine:
    return sa.create_engine(
        f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
        f"?connect_timeout=5",
        poolclass=sa.pool.NullPool,
    )


def _wait_ready(host: str, port: int, user: str, password: str, tries: int = 60) -> None:
    engine = _connect(host, port, user, password, "postgres")
    for _ in range(tries):
        try:
            with engine.begin() as conn:
                ready = conn.execute(sa.text("SELECT 1")).scalar() == 1
            if ready:
                engine.dispose()
                return
        except Exception:
            pass
        time.sleep(2)
    engine.dispose()
    raise RuntimeError(f"server {host}:{port} not ready after {tries * 2}s")


def _ensure_database(host: str, port: int, user: str, password: str, name: str) -> None:
    engine = _connect(host, port, user, password, "postgres")
    with engine.begin() as conn:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM pg_database WHERE datname = :n"
        ), {"n": name}).scalar()
        if not exists:
            conn.execute(sa.text("COMMIT"))
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-suite", action="store_true")
    parser.add_argument("--port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    args = parser.parse_args()

    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = args.port
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "traderaig")

    os.environ["POSTGRES_HOST"] = host
    os.environ["POSTGRES_PORT"] = str(port)
    os.environ["POSTGRES_USER"] = user
    os.environ["POSTGRES_PASSWORD"] = password
    os.environ["POSTGRES_DB"] = db
    os.environ["TRADERAIG_PERSIST"] = "1"

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    from persistence.db import engine, ensure_schema, make_live_session

    _wait_ready(host, port, user, password)
    _ensure_database(host, port, user, password, db)

    ensure_schema()
    assert engine.url.get_backend_name() == "postgresql", (
        f"engine backend must be postgresql, got {engine.url.get_backend_name()}"
    )
    with engine.begin() as conn:
        tables = set(conn.execute(sa.text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )).scalars())
    assert tables, "no tables created on PostgreSQL"
    required = {"users", "experiences", "risk_vetoes", "ops_runs", "audit"}
    missing = required - tables
    assert not missing, f"schema missing on PostgreSQL: {sorted(missing)}"

    session = make_live_session()
    session.close()

    print(f"[postgres-deploytest] server {host}:{port}, backend=postgresql, "
          f"db={db}, tables={len(tables)}")

    if args.no_suite:
        return 0

    import pytest

    rc = pytest.main(["tests", "-q", "-p", "no:cacheprovider"])
    print(f"[postgres-deploytest] full suite on PostgreSQL exited {rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
