"""Compile the MQL5 EA for real, when a runnable terminal is present.

This test exists because a source-code reading of `TraderAIG.mq5` said
"looks fine" while the file did not compile: the market publisher built a
nested `CJAVal` object, passed an `input int` where `ENUM_TIMEFRAMES` was
required, assigned to an array of `CJAVal`, and called `FolderExists()`,
which does not exist in MQL5. 27 errors. Only a real compiler catches that
class of mistake.

The guards are inside the test body on purpose. A `skipif` marker computed at
import time did not skip on the Windows CI runner: the test ran with no
MetaEditor and reported `FileNotFoundError: ... 'None'` as a failure. A
missing or unrunnable terminal must never turn into a red build, and a
*compile error* must never be swallowed as one, so:

- no MetaEditor found, or one that will not start -> skipped, with the reason;
- a compiler that ran and wrote a log -> asserted, 0 errors required.

Point `TRADERAIG_METAEDITOR` at a different MetaEditor64.exe to override
discovery. The compile happens inside the gitignored `mt5-portable` tree
precisely so compiling never dirties the working tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EA = ROOT / "mt5" / "TraderAIG.mq5"
PORTABLE = ROOT / "mt5-portable"


def _candidate_editors() -> list[Path]:
    override = os.environ.get("TRADERAIG_METAEDITOR", "").strip()
    candidates = [Path(override)] if override else []
    candidates.append(PORTABLE / "MetaEditor64.exe")
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                      / "MetaTrader 5" / "metaeditor64.exe")
    return candidates


def _resolve_metaeditor() -> Path | None:
    for cand in _candidate_editors():
        if cand.is_file():
            return cand
    return None


def _terminal_has_includes() -> bool:
    r"""`#include <Trade\Trade.mqh>` resolves only against an installed terminal."""
    return (PORTABLE / "MQL5" / "Include" / "Trade" / "Trade.mqh").is_file()


def _read_log(path: Path) -> str:
    """MetaEditor writes the log as UTF-16 with a BOM, not UTF-8."""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def test_metaeditor_discovery_reports_none_when_absent(tmp_path: Path) -> None:
    """The "no terminal" answer must be a real None, not a truthy stub.

    Guarding the guard: the CI failure above was a guard that returned a value
    the caller then handed to subprocess as `'None'`.
    """
    missing = tmp_path / "no-such-metaeditor.exe"
    assert missing.is_file() is False
    resolved: Path | None = None
    for cand in (missing, tmp_path / "also-missing.exe"):
        if cand.is_file():
            resolved = cand
    assert resolved is None


def test_ea_compiles_with_zero_errors(tmp_path: Path) -> None:
    """The EA must build cleanly on a real terminal."""
    editor = _resolve_metaeditor()
    if editor is None:
        pytest.skip("no MetaEditor64.exe found (set TRADERAIG_METAEDITOR to use one)")
    if not _terminal_has_includes():
        pytest.skip(f"{PORTABLE} has no MQL5 includes, so #include resolves nowhere")
    assert EA.is_file(), "mt5/TraderAIG.mq5 is missing"

    experts = PORTABLE / "MQL5" / "Experts"
    experts.mkdir(parents=True, exist_ok=True)
    target = experts / EA.name
    shutil.copy2(EA, target)
    log = tmp_path / "compile.log"

    try:
        proc = subprocess.run(
            [str(editor), f"/compile:{target}", f"/log:{log}"],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except OSError as exc:  # present on disk, will not start here
        pytest.skip(f"MetaEditor found at {editor} but will not run here: {exc}")

    assert log.is_file(), (
        "MetaEditor exited "
        f"{proc.returncode} without writing a log, so nothing was compiled and "
        "this is not a pass"
    )
    text = _read_log(log)
    assert "Result:" in text, f"compiler produced no Result line:\n{text}"

    result_line = next(ln for ln in text.splitlines() if ln.startswith("Result:"))
    error_count = int(result_line.split()[1])
    assert error_count == 0, (
        f"{error_count} compile error(s) in TraderAIG.mq5:\n"
        + "\n".join(ln for ln in text.splitlines() if ": error" in ln)
    )

    built = experts / (EA.stem + ".ex5")
    assert built.is_file(), "0 errors reported but no .ex5 was produced"
    assert built.stat().st_mtime >= target.stat().st_mtime, (
        "the .ex5 is older than the source it was built from: a stale binary"
    )


def test_ea_does_not_gate_publishing_on_a_reported_last_trade() -> None:
    """The live attach found this: FTTrading's BTCUSD fills bid/ask only.

    `last=0.0` on every tick of the symbol the operator actually trades, and
    the publisher required `last > 0` before it would write anything. The EA
    looked healthy, was loaded, and published nothing at all. Two real sides
    is the usability test; `last` is not part of it.
    """
    src = EA.read_text(encoding="utf-8", errors="replace")
    assert "if(last <= 0.0 || bid <= 0.0 || ask <= 0.0)" not in src
    assert "if(bid <= 0.0 || ask <= 0.0)" in src, (
        "the two-sided quote test should stand on bid/ask alone"
    )
    # the mid substitution is declared, not silent
    assert "last_source" in src
    assert "(bid + ask) / 2.0" in src


def test_ea_publishes_the_chart_symbol_not_the_trading_filter() -> None:
    """Second live-attach defect: the publisher followed InpSymbolFilter.

    On the operator's BTCUSD chart, `g_symbol = InpSymbolFilter` (XAUUSD) sent
    the market publisher looking for XAUUSD ticks. It found none, wrote
    nothing, and logged nothing - a healthy-looking EA publishing no market at
    all. The data path must be the symbol the chart is actually streaming;
    InpSymbolFilter stays a trading decision.
    """
    src = EA.read_text(encoding="utf-8", errors="replace")
    assert "g_marketSymbol = _Symbol;" in src

    start = src.index("string MarketFrameJson()")
    end = src.index("//| Timer (fallback if tick frequency is low)")
    market_region = src[start:end]
    assert "g_marketSymbol" in market_region
    assert "g_symbol" not in market_region, (
        "the market publisher must not read the trading filter symbol"
    )
    # ...and the trading path still gates on the filter
    assert "trade.PositionOpen(g_symbol" in src


def test_ea_writes_inside_the_mql5_sandbox_with_the_common_flag() -> None:
    """Third live-attach defect: the write path was outside the sandbox.

    MQL5 refuses to write outside its own folders, and with FILE_COMMON it
    resolves a *relative* path against `<TERMINAL_COMMONDATA_PATH>\\Files`. A
    live attach proved it empirically: an absolute path under Common returned
    err 5002 from both FolderCreate and FileOpen, while a probe file in the
    common root wrote fine. So the frame path must be relative.
    """
    src = EA.read_text(encoding="utf-8", errors="replace")
    assert "FILE_COMMON" in src
    assert 'string relDir     = InpMarketSubDir;' in src, (
        "the market dir must be a relative path resolved under the common root"
    )
    assert 'string filePath   = relDir + "\\\\" + g_marketSymbol + ".json";' in src
    assert "FolderCreate(dir, FILE_COMMON)" not in src, (
        "FolderCreate on the absolute path is what failed with err 5002"
    )
    # a failed write must say why, and must not retry on every tick
    assert "cannot write %s (err %d)" in src
    assert "commonRootWritable" in src


def test_ea_frame_json_uses_no_uncompilable_constructs() -> None:
    """Guard the exact constructs that broke the build, as source facts.

    A reader of this file could not tell those 27 errors were there. These
    assertions are cheap and specific, so a future edit that reintroduces one
    of them fails a test instead of waiting for a terminal.
    """
    src = EA.read_text(encoding="utf-8", errors="replace")

    # `FolderExists` does not exist in MQL5; only FolderCreate does.
    assert "FolderExists" not in src
    # Nested `CJAVal` objects and `CJAVal` arrays do not compile against the
    # Json.mqh shipped with the terminal (flat key/value pairs only).
    assert "CJAVal bars" not in src
    # `input int` is not an ENUM_TIMEFRAMES: the built-ins need a cast.
    for call in ("iOpen", "iHigh", "iLow", "iClose", "iVolume"):
        for line in src.splitlines():
            if call + "(" in line and "g_symbol" in line:
                assert "(ENUM_TIMEFRAMES)InpMarketTimeframe" in line, (
                    f"{call} is called with a raw input int: {line.strip()}"
                )
