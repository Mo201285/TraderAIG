"""The ledger is keyed by `record_id`: a replay updates, it does not copy.

The MT5 history sync re-reads the same closed deals every cycle. Before this
rule, each cycle appended another copy to the in-memory ledger while the
database (which upserts by the same id) stayed clean -- so storage looked
right and every read of memory reported thousands of closes for a few dozen
real deals.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.experience import ExperienceLedger, ExperienceRecord  # noqa: E402


def _record(rid="mt5:1", pnl=1.0, owner=""):
    return ExperienceRecord(
        record_id=rid,
        decision_id=f"deal:{rid}",
        timestamp=1000.0,
        actual_result={"pnl": pnl, "filled": True},
        owner_user_id=owner,
    )


def _ledger():
    led = ExperienceLedger()
    led._persist = lambda record: None
    return led


def test_recording_the_same_id_twice_stores_one_record():
    led = _ledger()
    assert led.record(_record(pnl=1.0)) is True
    assert led.record(_record(pnl=2.0)) is False

    rows = led.all()
    assert len(rows) == 1
    assert rows[0].actual_result["pnl"] == 2.0


def test_a_replay_does_not_duplicate_the_owner_bucket():
    led = _ledger()
    led._by_owner["u1"] = []
    led.record(_record(owner="u1"))
    led.record(_record(owner="u1"))

    assert len(led.list(owner_user_id="u1")) == 1


def test_distinct_ids_are_still_separate_records():
    led = _ledger()
    led.record(_record("mt5:1"))
    led.record(_record("mt5:2"))

    assert len(led.all()) == 2
    assert led.by_candidate("missing") == []
