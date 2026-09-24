"""Core logging handler tests (SafeRotatingFileHandler)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import logging
import os

import pytest

from core.logging import SafeRotatingFileHandler


def test_rotation_works_when_file_is_free(tmp_path):
    handler = SafeRotatingFileHandler(
        str(tmp_path / "system.log"),
        maxBytes=512, backupCount=2, encoding="utf-8")
    record = logging.LogRecord("t", logging.INFO, "f", 1, "x" * 200, None, None)
    handler.handle(record)
    assert Path(handler.baseFilename).exists()
    handler.handle(record)
    handler.handle(record)
    handler.handle(record)
    logs = sorted(tmp_path.glob("system.log*"))
    assert len(logs) >= 2
    handler.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows file-lock semantics")
def test_rotation_falls_back_when_primary_locked(tmp_path):
    primary = tmp_path / "system.log"
    handler = SafeRotatingFileHandler(
        str(primary), maxBytes=512, backupCount=2, encoding="utf-8")
    record = logging.LogRecord("t", logging.INFO, "f", 1, "x" * 200, None, None)
    handler.handle(record)
    _first = Path(handler.baseFilename)
    # Hold the primary open from a *different* descriptor to simulate another
    # process (e.g. the API server) having it open on Windows.
    lock = open(primary, "a", encoding="utf-8")
    try:
        handler.handle(record)          # grows primary past maxBytes
        handler.handle(record)          # triggers doRollover -> locked
    finally:
        lock.close()
    # The locked rollover must have switched to a per-process sidecar file.
    assert Path(handler.baseFilename) != primary
    assert Path(handler.baseFilename).exists()
    handler.close()
