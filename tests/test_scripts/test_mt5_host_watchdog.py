"""Tests for the market-data liveness watchdog.

The point of these tests is the one the project already paid for in blood: a
running terminal is not evidence of data. The verdict must come from frame
freshness, and the restart path must be rate limited so it cannot loop.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import mt5_host_watchdog as wd  # noqa: E402


def _write_frame(directory: Path, name: str, age: float, now: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"symbol": "BTCUSD"}), encoding="utf-8")
    stamp = now - age
    os.utime(path, (stamp, stamp))
    return path


def test_missing_directory_reports_no_age(tmp_path):
    assert wd.newest_frame_age(tmp_path / "nope") is None


def test_empty_directory_is_missing(tmp_path):
    assert wd.classify(wd.newest_frame_age(tmp_path), max_age=90.0) == "missing"


def test_newest_frame_wins_over_older_siblings(tmp_path):
    now = time.time()
    _write_frame(tmp_path, "BTCUSD.json", age=5.0, now=now)
    _write_frame(tmp_path, "EURUSD.json", age=90.0, now=now)
    assert wd.newest_frame_age(tmp_path, now=now) == pytest.approx(5.0, abs=1.0)


def test_classify_boundary_is_inclusive(tmp_path):
    now = time.time()
    _write_frame(tmp_path, "BTCUSD.json", age=90.0, now=now)
    age = wd.newest_frame_age(tmp_path, now=now)
    assert wd.classify(age, max_age=90.0) == "fresh"
    assert wd.classify(age + 1.0, max_age=90.0) == "stale"


def test_restart_budget_limits_per_hour():
    state = {"restarts": []}
    now = time.time()
    for _ in range(3):
        assert wd.restart_allowed(state, now=now, per_hour=3, cooldown=0.0) is True
        wd.record_restart(state, now)
    assert wd.restart_allowed(state, now=now, per_hour=3, cooldown=0.0) is False


def test_restart_budget_honours_cooldown():
    state = {"restarts": []}
    now = time.time()
    wd.record_restart(state, now)
    assert wd.restart_allowed(state, now=now + 10.0, per_hour=5, cooldown=120.0) is False
    assert wd.restart_allowed(state, now=now + 130.0, per_hour=5, cooldown=120.0) is True


def test_restart_budget_forgets_old_stamps():
    state = {"restarts": [0.0, 10.0]}
    wd.record_restart(state, time.time())
    assert state["restarts"] == [pytest.approx(time.time(), abs=5.0)]


def test_resolve_market_dir_uses_configured_common_data(monkeypatch, tmp_path):
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    resolved = wd.resolve_market_dir()
    assert resolved == tmp_path / "market"


@pytest.mark.skipif(os.name != "nt", reason="windows terminal layout only")
def test_resolve_market_dir_defaults_to_real_terminal_dir(monkeypatch, tmp_path):
    files = tmp_path / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
    files.mkdir(parents=True)
    monkeypatch.delenv("MT5_COMMON_DATA", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert wd.resolve_market_dir() == files / "market"


def test_ensure_terminal_starts_a_down_terminal(monkeypatch, tmp_path, capsys):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_text("", encoding="utf-8")
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(terminal))
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: False)
    launched = []
    monkeypatch.setattr(wd, "restart_terminal", lambda p: launched.append(p) or True)
    assert wd.main(["--ensure-terminal"]) == 0
    assert launched == [terminal]
    assert "launched" in capsys.readouterr().out


def test_ensure_terminal_does_not_double_start(monkeypatch, tmp_path):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_text("", encoding="utf-8")
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(terminal))
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: True)
    monkeypatch.setattr(wd, "restart_terminal", lambda *_a: pytest.fail("must not start twice"))
    assert wd.main(["--ensure-terminal"]) == 0


def test_terminal_path_expands_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(tmp_path))
    assert wd.resolve_terminal_path() == tmp_path / wd.DEFAULT_EXE
    monkeypatch.delenv("MT5_TERMINAL_PATH", raising=False)
    assert wd.resolve_terminal_path() is None


def test_terminal_flag_overrides_environment(monkeypatch, tmp_path):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_text("", encoding="utf-8")
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setenv("MT5_TERMINAL_PATH", r"D:\wrong\terminal64.exe")
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: False)
    launched = []
    monkeypatch.setattr(wd, "restart_terminal", lambda p: launched.append(p) or True)
    assert wd.main(["--ensure-terminal", "--terminal", str(terminal)]) == 0
    assert launched == [terminal]


def test_main_reports_fresh_frames(monkeypatch, tmp_path, capsys):
    now = time.time()
    _write_frame(tmp_path / "market", "BTCUSD.json", age=2.0, now=now)
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: True)
    assert wd.main(["--state", str(tmp_path / "state.json")]) == 0
    assert "OK frames_fresh" in capsys.readouterr().out


def test_main_flags_stale_frames_without_restarting(monkeypatch, tmp_path, capsys):
    now = time.time()
    _write_frame(tmp_path / "market", "BTCUSD.json", age=600.0, now=now)
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(tmp_path / "terminal64.exe"))
    monkeypatch.setattr(wd, "restart_terminal", lambda *_a, **_k: pytest.fail("must not restart"))
    assert wd.main(["--state", str(tmp_path / "state.json")]) == 1
    out = capsys.readouterr().out
    assert "STALE" in out and "report-only" in out


def test_main_restarts_only_when_asked(monkeypatch, tmp_path):
    now = time.time()
    _write_frame(tmp_path / "market", "BTCUSD.json", age=600.0, now=now)
    terminal = tmp_path / "terminal64.exe"
    terminal.write_text("", encoding="utf-8")
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(terminal))
    launched = []
    monkeypatch.setattr(wd, "restart_terminal", lambda p: launched.append(p) or True)
    state = tmp_path / "state.json"
    assert wd.main(["--restart", "--state", str(state)]) == 3
    assert launched == [terminal]
    assert wd.main(["--restart", "--state", str(state)]) == 1
    assert len(launched) == 1


def test_max_age_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MT5_WATCHDOG_MAX_AGE", "45")
    assert wd._parse_args([]).max_age == 45.0
    assert wd._parse_args(["--max-age", "10"]).max_age == 10.0
    monkeypatch.delenv("MT5_WATCHDOG_MAX_AGE", raising=False)
    assert wd._parse_args([]).max_age == wd.DEFAULT_MAX_AGE


def test_main_reports_configuration_error_when_market_dir_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path / "missing"))
    assert wd.main(["--state", str(tmp_path / "state.json")]) == 2


def test_log_file_records_every_run(monkeypatch, tmp_path):
    now = time.time()
    _write_frame(tmp_path / "market", "BTCUSD.json", age=2.0, now=now)
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: True)
    log = tmp_path / "logs" / "watchdog.log"
    args = ["--log", str(log), "--state", str(tmp_path / "state.json")]
    assert wd.main(args) == 0
    _write_frame(tmp_path / "market", "BTCUSD.json", age=600.0, now=now)
    assert wd.main(args) == 1
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "frames_fresh" in lines[0] and "STALE" in lines[1] and "report-only" in lines[2]


def test_log_failure_never_changes_the_verdict(monkeypatch, tmp_path, capsys):
    now = time.time()
    _write_frame(tmp_path / "market", "BTCUSD.json", age=2.0, now=now)
    monkeypatch.setenv("MT5_COMMON_DATA", str(tmp_path))
    monkeypatch.setattr(wd, "terminal_running", lambda *_a, **_k: True)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    assert wd.main(["--log", str(blocker / "watchdog.log")]) == 0
    assert "could not write log" in capsys.readouterr().err
