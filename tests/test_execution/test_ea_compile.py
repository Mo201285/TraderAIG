"""Compile the MQL5 EA for real, when a terminal is installed.

This test exists because a source-code reading of `TraderAIG.mq5` said
"looks fine" while the file did not compile: the market publisher built a
nested `CJAVal` object, passed an `input int` where `ENUM_TIMEFRAMES` was
required, assigned to an array of `CJAVal`, and called `FolderExists()`,
which does not exist in MQL5. 27 errors. The only thing that catches that
class of mistake is a real compiler.

Skipped when no terminal is present (CI, and any operator without MT5), so it
never turns a missing MetaEditor into a red build. Point
`TRADERAIG_METAEDITOR` at a different MetaEditor64.exe to override discovery.
The compile happens inside the gitignored `mt5-portable` tree precisely so a
compile never dirties the working tree.
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


def _metaeditor() -> Path | None:
    override = os.environ.get("TRADERAIG_METAEDITOR", "").strip()
    candidates = [Path(override)] if override else []
    candidates += [
        PORTABLE / "MetaEditor64.exe",
        Path(r"C:\Program Files\MetaTrader 5\metaeditor64.exe"),
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _terminal_has_includes() -> bool:
    return (PORTABLE / "MQL5" / "Include" / "Trade" / "Trade.mqh").is_file()


METAEDITOR = _metaeditor()

requires_terminal = pytest.mark.skipif(
    METAEDITOR is None,
    reason="no MetaEditor64.exe found (set TRADERAIG_METAEDITOR to compile)",
)
requires_includes = pytest.mark.skipif(
    not _terminal_has_includes(),
    reason="mt5-portable has no MQL5 includes, so #include resolves nowhere",
)


@requires_terminal
@requires_includes
def _read_log(path: Path) -> str:
    """MetaEditor writes the log as UTF-16 with a BOM, not UTF-8."""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def test_ea_compiles_with_zero_errors(tmp_path: Path) -> None:
    """The EA must build cleanly on a real terminal."""
    assert EA.is_file(), "mt5/TraderAIG.mq5 is missing"
    experts = PORTABLE / "MQL5" / "Experts"
    experts.mkdir(parents=True, exist_ok=True)
    target = experts / EA.name
    shutil.copy2(EA, target)
    log = tmp_path / "compile.log"
    if log.exists():
        log.unlink()

    proc = subprocess.run(
        [str(METAEDITOR), f"/compile:{target}", f"/log:{log}"],
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert log.is_file(), (
        "MetaEditor wrote no log (exit "
        f"{proc.returncode}); the compiler never ran, so this is a harness "
        "problem, not a pass"
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
