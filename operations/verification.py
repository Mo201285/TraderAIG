"""Verification artifact: the measured gate result behind the Developer Hub.

Spec section 8 (Developer Home) asks the surface to show Build PASS + the
measured test count **from the live run, never a hard-coded number**. The one
place a real run happens is ``scripts/verify_all.ps1``; this module is the
storage seam between that run and ``GET /system/verification``.

The PowerShell gate writes what it measured (one JSON blob on stdin); this
module normalises it, parses the pytest summary it captured, and stores it
atomically. The route only ever *reads* the artifact: if no run has been
recorded the surface shows an absent state rather than an invented green.
Nothing here can execute a gate, so a dashboard can never manufacture a PASS.

``TRADERAIG_VERIFICATION_PATH`` overrides the artifact location (same knob
shape as ``TRADERAIG_DB_PATH``) so tests never touch the live host's file.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# Canonical gate order; the surface renders in exactly this sequence.
ORDER = ("ruff", "compile", "pytest", "tsc", "vite", "smoke")

_PYTEST_COUNTS = (
    ("passed", r"(\d+)\s+passed"),
    ("failed", r"(\d+)\s+failed"),
    ("errors", r"(\d+)\s+errors?"),
    ("skipped", r"(\d+)\s+skipped"),
)
_PYTEST_SECONDS = re.compile(r"\bin\s+([\d.]+)s")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact_path() -> Path:
    explicit = os.getenv("TRADERAIG_VERIFICATION_PATH")
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parent.parent / ".data" / "verification.json"


def parse_pytest_summary(text: str) -> Dict[str, float]:
    """Pull the measured counts out of a captured ``pytest -q`` run.

    Returns ``passed`` / ``failed`` / ``errors`` / ``skipped`` (0 when the line
    does not mention them), a derived ``total``, and ``seconds`` when present.
    Absent counts are 0 by omission: a run that reported no failures genuinely
    reported none, but a run this module never saw reports nothing at all
    (``present: False`` at the view layer).
    """
    out: Dict[str, float] = {name: 0 for name, _ in _PYTEST_COUNTS}
    for name, pattern in _PYTEST_COUNTS:
        match = re.search(pattern, text or "")
        if match:
            out[name] = int(match.group(1))
    seconds = _PYTEST_SECONDS.search(text or "")
    if seconds:
        out["seconds"] = float(seconds.group(1))
    out["total"] = sum(
        int(out[k]) for k in ("passed", "failed", "errors", "skipped")
    )
    return out


def normalize_gates(raw: Dict) -> Dict[str, Dict]:
    """Keep only the canonical gates, in order, in a stable shape."""
    gates: Dict[str, Dict] = {}
    if not isinstance(raw, dict):
        return gates
    for code in ORDER:
        entry = raw.get(code)
        if not isinstance(entry, dict):
            continue
        out = {"ok": bool(entry.get("ok"))}
        detail = entry.get("detail")
        if detail:
            out["detail"] = str(detail)
        if code == "pytest":
            summary = parse_pytest_summary(out.get("detail", ""))
            for key in ("passed", "failed", "errors", "skipped", "total"):
                out[key] = int(summary.get(key, 0))
            if "seconds" in summary:
                out["seconds"] = summary["seconds"]
        gates[code] = out
    return gates


def record(payload: Dict, path: Optional[Path] = None) -> Dict:
    """Persist one measured run. Atomic write; never raises on I/O."""
    gates = normalize_gates((payload or {}).get("gates") or {})
    selected = [str(x) for x in ((payload or {}).get("selected") or [])]
    doc = {
        "generated_at": (payload or {}).get("generated_at") or _now(),
        "source": "verify_all.ps1",
        "selected": selected,
        "gates": gates,
    }
    target = path or _artifact_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, target)
    return doc


def _empty(error: str = "") -> Dict:
    view = {
        "ok": True,
        "present": False,
        "generated_at": None,
        "source": "",
        "gates": {},
        "summary": {"gates_total": 0, "passed": 0, "failed": 0},
    }
    if error:
        view["error"] = error
    return view


def latest(path: Optional[Path] = None) -> Dict:
    """Read the last recorded verification. Never raises; absent => present:False."""
    target = path or _artifact_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty("")
    except OSError as exc:  # noqa: BLE001 - report, never 500 the route
        return _empty(str(exc))
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return _empty(f"unreadable artifact: {exc}")
    if not isinstance(doc, dict) or not doc:
        return _empty("")
    gates = normalize_gates(doc.get("gates") or {})
    passed = sum(1 for gate in gates.values() if gate.get("ok"))
    return {
        "ok": True,
        "present": True,
        "generated_at": doc.get("generated_at") or None,
        "source": str(doc.get("source") or ""),
        "gates": gates,
        "summary": {
            "gates_total": len(gates),
            "passed": passed,
            "failed": len(gates) - passed,
        },
    }


def main(argv: Optional[list] = None) -> int:
    """CLI seam used by ``scripts/verify_all.ps1``.

    ``record`` reads a JSON blob from stdin (or a positional arg) and stores it;
    with no arguments the current view is printed so an operator can inspect it.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "record":
        blob = args[1] if len(args) > 1 else sys.stdin.read()
        try:
            payload = json.loads(blob or "{}")
        except ValueError as exc:
            print(f"verification: invalid payload: {exc}")
            return 2
        doc = record(payload)
        print(f"verification: recorded {len(doc['gates'])} gate(s)")
        return 0
    print(json.dumps(latest(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the route
    raise SystemExit(main())
