"""SQLite durability pragmas on the session engine.

`persistence/db.py` opens the live database with WAL and an explicit busy
timeout. Both are asserted on the engine the suite actually holds, not on a
freshly built one: a pragma applied to an engine nobody uses is a setting, not
a behaviour.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from persistence.db import engine  # noqa: E402


def _pragma(name: str) -> object:
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_file_backed_sqlite_runs_in_wal_mode():
    assert engine.url.get_backend_name() == "sqlite"
    assert _pragma("journal_mode") == "wal"


def test_busy_timeout_is_explicit():
    assert _pragma("busy_timeout") == 5000
