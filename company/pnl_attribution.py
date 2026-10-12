"""Company P&L attribution (S8 AI Company).

The experience ledger's realised PnL is already attributed **per strategy** by
``learning.performance.PerformanceAttributor`` (M8.5). This module is the
*company* view over that same evidence: it rolls each strategy's realised PnL up
to its **desk** (the strategy family) and to its accountable **owner** (the
RMI-05 asset-metadata ``owner``), so the AI company's revenue has a name on it.

Honesty rules, shared with the rest of the platform:

* **Attribution is explicit.** A strategy with no recorded owner rolls into the
  ``unattributed`` bucket -- never silently dropped -- so the owner and desk
  rollups always reconcile to the company total.
* **No fabricated numbers.** A strategy's realised PnL is reported as the sum of
  its actual results; a strategy (or desk/owner) with fewer than ``MIN_SAMPLES``
  trades is marked ``proven=False`` rather than dressed up as a track record.
* **Read-only, never a gate.** This is an accountability surface; it holds no
  trade authority (``trade_authority`` = the Risk Governor).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from learning.performance import PerformanceAttributor


log = get_logger("company.pnl_attribution")


MIN_SAMPLES = 3
UNATTRIBUTED = "unattributed"


def _owner_of(asset) -> str:
    if asset is None:
        return UNATTRIBUTED
    owner = str((getattr(asset, "metadata", None) or {}).get("owner") or "").strip()
    return owner or UNATTRIBUTED


def _desk_of(asset) -> str:
    if asset is None:
        return UNATTRIBUTED
    family = getattr(asset, "family", None)
    value = getattr(family, "value", None) or str(family or "")
    return value.strip() or UNATTRIBUTED


class PnLAttribution:
    """Roll the experience ledger's per-strategy PnL up to desk and owner."""

    def __init__(self, *, ledger_ref=None, asset_layer=None,
                 attributor: Optional[PerformanceAttributor] = None) -> None:
        if attributor is not None:
            self._attributor = attributor
        elif ledger_ref is not None:
            self._attributor = PerformanceAttributor(ledger_ref)
        else:
            from learning.performance import attributor as _default
            self._attributor = _default
        self._assets = asset_layer

    def _layer(self, asset_layer=None):
        return asset_layer if asset_layer is not None else self._assets

    def by_strategy(self, *, ownership: Optional[str] = None,
                    asset_layer=None) -> List[Dict[str, Any]]:
        """Per-strategy PnL enriched with its desk and accountable owner."""
        layer = self._layer(asset_layer)
        rows = self._attributor.by_strategy(ownership=ownership)
        out: List[Dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("strategy_id"))
            asset = None
            if layer is not None and sid != UNATTRIBUTED:
                try:
                    asset = layer.asset(sid)
                except Exception:  # noqa: BLE001
                    asset = None
            trades = int(row.get("total_trades") or 0)
            out.append({
                "strategy_id": sid,
                "desk": _desk_of(asset),
                "owner": _owner_of(asset),
                "total_trades": trades,
                "winning_trades": row.get("winning_trades", 0),
                "losing_trades": row.get("losing_trades", 0),
                "gross_pnl": row.get("gross_pnl", 0.0),
                "net_pnl": row.get("net_pnl", 0.0),
                "win_rate": row.get("win_rate", 0.0),
                "profit_factor": row.get("profit_factor", 0.0),
                "max_drawdown": row.get("max_drawdown", 0.0),
                "proven": trades >= MIN_SAMPLES,
            })
        out.sort(key=lambda r: r["net_pnl"], reverse=True)
        return out

    def _rollup(self, rows: List[Dict[str, Any]], key: str,
                extra_key: str) -> List[Dict[str, Any]]:
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = row[key]
            b = buckets.setdefault(name, {
                key: name, "net_pnl": 0.0, "trades": 0, "strategies": 0,
                "proven": True, extra_key + "s": set(),
            })
            b["net_pnl"] += row["net_pnl"]
            b["trades"] += row["total_trades"]
            b["strategies"] += 1
            if not row["proven"]:
                b["proven"] = False
            b[extra_key + "s"].add(row[extra_key])
        out: List[Dict[str, Any]] = []
        for b in buckets.values():
            b["net_pnl"] = round(b["net_pnl"], 2)
            b["proven"] = b["proven"] and b["trades"] >= MIN_SAMPLES
            b[extra_key + "s"] = sorted(b[extra_key + "s"])
            out.append(b)
        out.sort(key=lambda r: r["net_pnl"], reverse=True)
        return out

    def by_desk(self, *, ownership: Optional[str] = None,
                asset_layer=None) -> List[Dict[str, Any]]:
        return self._rollup(self.by_strategy(ownership=ownership,
                                             asset_layer=asset_layer),
                            "desk", "owner")

    def by_owner(self, *, ownership: Optional[str] = None,
                 asset_layer=None) -> List[Dict[str, Any]]:
        return self._rollup(self.by_strategy(ownership=ownership,
                                             asset_layer=asset_layer),
                            "owner", "desk")

    def report(self, *, ownership: Optional[str] = None,
               asset_layer=None) -> Dict[str, Any]:
        """The company P&L attribution report (read-only, reconcilable)."""
        rows = self.by_strategy(ownership=ownership, asset_layer=asset_layer)
        by_desk = self._rollup(rows, "desk", "owner")
        by_owner = self._rollup(rows, "owner", "desk")

        net = sum(r["net_pnl"] for r in rows)
        trades = sum(r["total_trades"] for r in rows)
        attributed = sum(r["net_pnl"] for r in rows if r["owner"] != UNATTRIBUTED)
        unattributed = round(net - attributed, 2)

        return {
            "generated_at": time.time(),
            "company": {
                "net_pnl": round(net, 2),
                "trades": trades,
                "strategies": len(rows),
                "desks": len(by_desk),
                "owners": len(by_owner),
                "attributed_pnl": round(attributed, 2),
                "unattributed_pnl": unattributed,
                "attribution_coverage": (
                    round(attributed / net, 4) if net else None),
            },
            "by_strategy": rows,
            "by_desk": by_desk,
            "by_owner": by_owner,
            "min_samples": MIN_SAMPLES,
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }


pnl_attribution = PnLAttribution()
