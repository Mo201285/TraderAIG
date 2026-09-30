"""Pytest configuration: isolate tests from live persistence/Redis."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure persistence hook is OFF for all tests.
os.environ["TRADERAIG_PERSIST"] = "0"
os.environ["TRADERAIG_STATE_REDIS"] = "0"

# Durable boards must never be written inside the repo by a test run.
os.environ["TRADERAIG_OPPORTUNITY_BOARD"] = os.path.join(
    tempfile.mkdtemp(prefix="traderaig-test-opp-"), "opportunities.json")

# The database, for the same reason and with the same force.
#
# Set at import time, before any test module can `import persistence.db`, because
# the engine is built once at that import from this variable. Every repository
# that writes through it -- governance, audit, and now the challenge baseline --
# would otherwise write into `.data/traderaig.db`, which is the *live* database
# of the 24/7 backend on this host. That is not a tidiness problem: a test that
# declares a `verified` opening balance for a real MT5 login leaves a fabricated
# baseline sitting in the live control plane, where nothing marks it as a test.
os.environ["TRADERAIG_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="traderaig-test-db-"), "test.db")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _challenge_schema():
    """Create the challenge tables once per session, not once per test.

    `ensure_schema()` inspects the engine and runs DDL checks; calling it from
    every test added several seconds to each one and took the suite from about
    seven minutes to twenty-eight, which is its own kind of failure -- a gate
    nobody runs is a gate nobody trusts.
    """
    from persistence.db import ensure_schema

    ensure_schema()
    yield


@pytest.fixture(autouse=True)
def _reset_challenge_store(_challenge_schema):
    """Challenge baselines are durable, so they outlive the test that made them.

    Without this, a test that declares a verified baseline for an account id
    leaves it in the session database, and the next test that observes the same
    id silently inherits a baseline it never asked for. That turns an ordering
    accident into a wrong answer: a test asserting "a watched account is not
    graded against an inferred opening balance" passes or fails depending on
    what ran before it. The market plane needs this for the same reason.
    """
    def _clean():
        from sqlalchemy import text

        from persistence.db import engine

        with engine.begin() as conn:
            for table in ("challenge_baselines", "challenge_states"):
                conn.execute(text(f"DELETE FROM {table}"))

    _clean()
    yield
    _clean()


@pytest.fixture(autouse=True)
def _isolate_market_plane():
    """The market plane is a process-wide singleton, so a test that publishes
    into it (or registers a fake feed) would otherwise leak into the next test
    and make feed precedence/freshness assertions order-dependent."""
    from core.market_plane import market_plane

    def _clean():
        market_plane.reset()
        market_plane.reset_counters()
        for source in market_plane.feeds():
            market_plane.unregister_feed(source)

    _clean()
    yield
    _clean()
