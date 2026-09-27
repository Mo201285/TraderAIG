"""Pytest configuration: isolate tests from live persistence/Redis."""

import os
import sys
import tempfile
from pathlib import Path

# Ensure persistence hook is OFF for all tests.
os.environ["TRADERAIG_PERSIST"] = "0"
os.environ["TRADERAIG_STATE_REDIS"] = "0"

# Durable boards must never be written inside the repo by a test run.
os.environ["TRADERAIG_OPPORTUNITY_BOARD"] = os.path.join(
    tempfile.mkdtemp(prefix="traderaig-test-opp-"), "opportunities.json")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
