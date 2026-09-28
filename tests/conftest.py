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

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


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
