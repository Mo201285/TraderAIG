"""Tests for the MT5 bridge directory contract.

One bug class is worth locking down here: a market poller that runs happily
against a directory the terminal does not write to. The EA writes with
`FILE_COMMON`, which lands in the real terminal's `Common\\Files`; the
developer's `bridge/` path is a different place entirely. When the default
resolved to `bridge/`, the 24/7 host reported an ACTIVE poller with 17 passes
and zero frames seen while the terminal published perfectly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from execution.bridge import MT5Bridge, terminal_common_files  # noqa: E402


def test_env_var_is_the_single_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    assert MT5Bridge().market_directory == tmp_path / "market"
    assert MT5Bridge().bridge_file == tmp_path / "TraderAIG_bridge.json"


def test_explicit_directory_is_never_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv("MT5_COMMON_DATA", raising=False)
    monkeypatch.setattr("execution.bridge.terminal_common_files",
                        lambda: Path(r"C:\real\terminal\Files"))
    bridge = MT5Bridge(directory=str(tmp_path / "scratch"))
    assert bridge.market_directory == tmp_path / "scratch" / "market"


def test_real_terminal_wins_over_the_developer_path(monkeypatch):
    from core.config import settings
    monkeypatch.delenv("MT5_COMMON_DATA", raising=False)
    monkeypatch.setattr("execution.bridge.terminal_common_files",
                        lambda: Path(r"C:\real\terminal\Files"))
    bridge = MT5Bridge()
    assert bridge.market_directory == Path(r"C:\real\terminal\Files\market")
    # The signal/command path must stay exactly where it was: only market
    # reads move, so an approved order can never be redirected by this change.
    assert bridge.bridge_file == settings.root_dir / "bridge" / "TraderAIG_bridge.json"


def test_developer_path_still_used_when_no_terminal_dir(monkeypatch):
    from core.config import settings
    monkeypatch.delenv("MT5_COMMON_DATA", raising=False)
    monkeypatch.setattr("execution.bridge.terminal_common_files", lambda: None)
    assert MT5Bridge().market_directory == settings.root_dir / "bridge" / "market"


@pytest.mark.skipif(sys.platform != "win32", reason="windows layout only")
def test_terminal_common_files_requires_the_dir_to_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert terminal_common_files() is None
    (tmp_path / "MetaQuotes" / "Terminal" / "Common" / "Files").mkdir(parents=True)
    assert terminal_common_files() == tmp_path / "MetaQuotes" / "Terminal" / "Common" / "Files"
