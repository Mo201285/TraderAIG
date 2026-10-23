"""The suite must not be able to write into the running system's own tables.

`tests/conftest.py` redirects `TRADERAIG_DB_PATH` to a temp file, and the engine
is built from that variable exactly once, at import. Every assertion in this
repository about test isolation therefore rests on a single environment variable
having reached that import -- which is the kind of protection that fails without
sounding like anything.

It did fail, silently, on this host. An `observed` baseline for MT5 login
1787174 and a `DemoProp` policy version were both found in `.data/traderaig.db`,
the live database of the 24/7 backend, written by a test run. Neither row said
"test". A fabricated `verified` opening balance has the same shape as the truth,
so the only place to stop it is before the write.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from suite_isolation import bound_to_the_live_database as _live  # noqa: E402

LIVE_URL = "sqlite:///D:/One/.data/traderaig.db"


def test_the_engine_the_suite_actually_holds_is_not_the_live_database():
    """The claim this whole file exists to defend, asserted against the engine.

    Not against what conftest *set*: the failure mode is precisely that the
    variable is set and then not honoured, so the only meaningful thing to read
    is the engine object every write will go through.
    """
    from persistence.db import engine

    assert not _live(str(engine.url)), (
        "the suite is writing through the live engine: %s" % engine.url)


def test_the_live_sqlite_path_is_recognised_however_it_is_spelled():
    assert _live(LIVE_URL)
    assert _live("sqlite:///D:\\One\\.data\\traderaig.db")


def test_a_temp_database_is_not_the_live_one():
    assert not _live(
        "sqlite:///C:/Users/x/AppData/Local/Temp/traderaig-test-db-abc/test.db")


def test_a_database_that_merely_mentions_the_name_is_still_caught():
    """`traderaig.db.bak-...` sits beside the live file and is a copy of it.

    Restoring from a backup of the live database is a reasonable thing for an
    operator to do and an unreasonable thing for a test run to do, so a path that
    merely contains the name is treated as live rather than waved through.
    """
    assert _live(
        "sqlite:///D:/One/.data/traderaig.db.bak-20261003-213158")


def test_a_configured_postgres_is_the_live_database_too(monkeypatch):
    """The SQLite default is not the only way to reach production storage."""
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    try:
        assert _live("postgresql+psycopg://u@h:5432/db")
    finally:
        monkeypatch.delenv("POSTGRES_HOST", raising=False)


def test_the_suite_does_not_log_into_the_live_desk_log_file():
    """`get_logger()` attaches a rotating file handler the first time a module
    asks for one, under `settings.logging.directory`. On this host that is the
    live desk's own `logs/`, so a suite run wrote synthetic fills -- `MT5 FILLED
    XAUUSD ... @ 2000.1` -- into the audit log beside the real ones, and the two
    are indistinguishable once written. `LOG_DIR` in conftest moves the suite's
    handler somewhere disposable; this reads the settings object the handlers
    actually use rather than the variable that was supposed to redirect it.
    """
    from core.config import ROOT_DIR, settings

    live = (ROOT_DIR / "logs").resolve()
    suite = Path(settings.logging.directory).resolve()
    assert suite != live, "the suite logs into the live desk's logs directory"
    assert live not in suite.parents, (
        "the suite's log directory is inside the live desk's logs directory")
