"""Pytest configuration: isolate tests from live persistence/Redis."""

import os
import sys
from pathlib import Path

# Ensure persistence hook is OFF for all tests.
os.environ["TRADERAIG_PERSIST"] = "0"
os.environ["TRADERAIG_STATE_REDIS"] = "0"

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
