"""S8 Company P&L attribution tests (row 783).

The attribution rolls realised PnL up from strategy to desk and accountable
owner. It is evidence-only: no fabricated track record, thin evidence is marked
unproven, and PnL with no recorded owner is surfaced as unattributed -- never
dropped -- so the company total always reconciles.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from learning.experience import ExperienceLedger, ExperienceRecord  # noqa: E402
from company.pnl_attribution import (  # noqa: E402
    MIN_SAMPLES,
    UNATTRIBUTED,
    PnLAttribution,
)


class _Enum:
    def __init__(self, value):
        self.value = value


class _Asset:
    def __init__(self, *, owner=None, family="ict"):
        self.metadata = {"owner": owner} if owner else {}
        self.family = _Enum(family)


class _Layer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


def _record(sid, pnl, seq, origin="system"):
    return ExperienceRecord(
        record_id=f"{sid}-{seq}", decision_id="d", timestamp=float(seq),
        metadata={"strategy_id": sid},
        actual_result={"pnl": pnl, "origin": origin},
    )


def _ledger(series_by_strategy, origin="system"):
    led = ExperienceLedger()
    seq = 0
    for sid, series in series_by_strategy.items():
        for pnl in series:
            led.record(_record(sid, pnl, seq, origin))
            seq += 1
    return led


def test_by_strategy_attributes_owner_and_desk():
    led = _ledger({"s1": [10.0, 20.0, -5.0], "s2": [-3.0, -3.0]})
    layer = _Layer({"s1": _Asset(owner="u1", family="trend"),
                    "s2": _Asset(owner="u2", family="ict")})
    rows = PnLAttribution(ledger_ref=led, asset_layer=layer).by_strategy()
    by_id = {r["strategy_id"]: r for r in rows}
    assert by_id["s1"]["owner"] == "u1"
    assert by_id["s1"]["desk"] == "trend"
    assert by_id["s1"]["net_pnl"] == 25.0
    assert by_id["s1"]["proven"] is True
    assert by_id["s2"]["owner"] == "u2"
    assert by_id["s2"]["proven"] is False  # only 2 trades


def test_no_recorded_owner_is_unattributed_never_dropped():
    led = _ledger({"s1": [10.0, 20.0, -5.0], "ghost": [5.0, 5.0, 5.0]})
    layer = _Layer({"s1": _Asset(owner="u1", family="trend")})
    report = PnLAttribution(ledger_ref=led, asset_layer=layer).report()
    ghost = [r for r in report["by_strategy"] if r["strategy_id"] == "ghost"][0]
    assert ghost["owner"] == UNATTRIBUTED
    assert ghost["desk"] == UNATTRIBUTED
    assert report["company"]["unattributed_pnl"] == 15.0


def test_owner_rollup_sums_desks_and_reconciles():
    led = _ledger({"s1": [10.0, 20.0, -5.0], "s2": [5.0, 5.0, 5.0]})
    layer = _Layer({"s1": _Asset(owner="u1", family="trend"),
                    "s2": _Asset(owner="u1", family="ict")})
    report = PnLAttribution(ledger_ref=led, asset_layer=layer).report()
    owners = {r["owner"]: r for r in report["by_owner"]}
    assert owners["u1"]["net_pnl"] == 40.0
    assert owners["u1"]["strategies"] == 2
    assert owners["u1"]["desks"] == ["ict", "trend"]
    assert owners["u1"]["proven"] is True
    # attributed + unattributed always equals the company net
    comp = report["company"]
    assert comp["attributed_pnl"] + comp["unattributed_pnl"] == comp["net_pnl"]
    assert comp["attribution_coverage"] == 1.0


def test_desk_rollup_lists_owners():
    led = _ledger({"s1": [1.0, 1.0, 1.0], "s2": [2.0, 2.0, 2.0]})
    layer = _Layer({"s1": _Asset(owner="u1", family="trend"),
                    "s2": _Asset(owner="u2", family="trend")})
    desks = {r["desk"]: r for r in PnLAttribution(
        ledger_ref=led, asset_layer=layer).by_desk()}
    assert desks["trend"]["net_pnl"] == 9.0
    assert desks["trend"]["owners"] == ["u1", "u2"]


def test_thin_evidence_is_not_proven():
    led = _ledger({"s1": [1.0, 1.0]})  # one short of MIN_SAMPLES
    layer = _Layer({"s1": _Asset(owner="u1", family="trend")})
    report = PnLAttribution(ledger_ref=led, asset_layer=layer).report()
    assert report["by_strategy"][0]["proven"] is False
    assert report["by_owner"][0]["proven"] is False
    assert MIN_SAMPLES == 3


def test_nothing_recorded_fabricates_nothing():
    report = PnLAttribution(ledger_ref=ExperienceLedger(),
                            asset_layer=_Layer({})).report()
    assert report["company"]["net_pnl"] == 0.0
    assert report["company"]["strategies"] == 0
    assert report["company"]["attribution_coverage"] is None
    assert report["by_strategy"] == []
    assert report["by_owner"] == []
    assert report["by_desk"] == []
    assert report["read_only"] is True
    assert report["is_authorisation"] is False
    assert report["trade_authority"] == "risk/governor.py"


def test_ownership_classes_are_never_merged():
    led = ExperienceLedger()
    seq = 0
    for origin in ("system", "manual"):
        for pnl in (1.0, 2.0, 3.0):
            led.record(_record("s1", pnl, seq, origin))
            seq += 1
    attr = PnLAttribution(ledger_ref=led,
                          asset_layer=_Layer({"s1": _Asset(owner="u1")}))
    system = attr.report(ownership="system")["company"]
    manual = attr.report(ownership="manual")["company"]
    assert system["net_pnl"] == 6.0
    assert manual["net_pnl"] == 6.0
    assert system["trades"] == 3
