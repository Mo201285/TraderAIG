"""Is this database the running system's own, or somewhere disposable?

The rule lives here rather than inline in `conftest.py` so that it can be tested
directly. A guard that can only be exercised by breaking the suite's isolation is
a guard nobody discovers is broken -- and this one had already broken silently
before anyone wrote a test for it.
"""
import os

LIVE_SQLITE_SUFFIX = "/.data/traderaig.db"


def bound_to_the_live_database(url: str) -> bool:
    """True when this engine URL addresses the live backend's own storage.

    Two answers count as live. The SQLite file the 24/7 backend reads and writes
    is one, and a configured Postgres is the other: `persistence/db.py` prefers
    `POSTGRES_HOST` over any SQLite path, so a suite run on a developer machine
    with that variable set is pointed at production storage no matter what
    `TRADERAIG_DB_PATH` says.

    The filename match is deliberately loose. A `.bak` copy of the live database
    sits beside it and contains the same rows, and restoring production data from
    a backup is a reasonable operator action and an unreasonable test action --
    so anything carrying the live name is treated as live rather than waved
    through because the suffix is not an exact match.
    """
    if os.getenv("POSTGRES_HOST"):
        return True
    return LIVE_SQLITE_SUFFIX in str(url).replace("\\", "/")
