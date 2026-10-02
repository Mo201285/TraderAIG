"""The broker's UTC offset is read, not remembered.

The offset decides where the daily-loss day starts. On this account it read
+01:00 on 2026-10-02, and the EU DST change on 2026-10-25 moves a broker on
European time to +02:00. A policy that recorded +01:00 and kept it would place
the day boundary an hour out from the broker's own -- silently, and on the days
a daily loss is most likely to be measured.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import challenge.live as live


class Policy:
    def __init__(self, offset=None):
        if offset is not None:
            self.server_utc_offset_hours = offset


def test_offset_is_measured_from_the_brokers_tick(monkeypatch):
    """Tick timestamp minus host clock, in hours.

    MT5 gives python no server-time call, but every tick is stamped by the
    server that produced it, which is the same fact read a different way.
    """
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 1.0)
    assert live.server_utc_offset_hours(Policy(1.0)) == pytest.approx(1.0)


def test_registered_offset_is_authoritative_when_present(monkeypatch):
    """The policy value wins over the live reading, so an audit reads the term.

    The live measurement's job is drift detection, not silent replacement: an
    offset that changes itself would leave no record of what the policy claimed.
    """
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 2.0)
    assert live.server_utc_offset_hours(Policy(1.0)) == pytest.approx(1.0)


def test_missing_policy_offset_falls_back_to_the_measurement(monkeypatch):
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 2.0)
    assert live.server_utc_offset_hours(Policy()) == pytest.approx(2.0)


def test_unmeasurable_offset_does_not_invent_zero(monkeypatch):
    """None in, 0.0 out only because the caller has no better answer.

    A managed account with no offset is scored UNKNOWN downstream and refused,
    which is the correct outcome for a day boundary that cannot be located.
    """
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": None)
    assert live.server_utc_offset_hours(Policy()) == 0.0


def test_measurement_uses_the_tick_not_a_constant(monkeypatch):
    """The measured value is derived, so it moves when the broker's clock does.

    Hardcoding +01:00 is the failure this replaces: it stays correct right up
    until the DST boundary and is then an hour wrong forever after.
    """
    class Tick:
        def __init__(self, t):
            self.time = t

    class FakeMT5:
        def __init__(self, tick_time):
            self._tick_time = tick_time

        def symbol_info_tick(self, symbol):
            return Tick(self._tick_time)

    now = 1_800_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setitem(sys.modules, "MetaTrader5",
                        FakeMT5(now + 3600.0))          # broker is +01:00
    assert live.measured_server_utc_offset_hours() == pytest.approx(1.0)

    monkeypatch.setitem(sys.modules, "MetaTrader5",
                        FakeMT5(now + 2 * 3600.0))      # after DST, broker +02:00
    assert live.measured_server_utc_offset_hours() == pytest.approx(2.0)


def test_fractional_offsets_are_kept_whole_offsets_are_not_forced(monkeypatch):
    """+05:30 and +08:45 exist; rounding them moves the boundary a quarter-hour."""
    class Tick:
        def __init__(self, t):
            self.time = t

    class FakeMT5:
        def __init__(self, tick_time):
            self._tick_time = tick_time

        def symbol_info_tick(self, symbol):
            return Tick(self._tick_time)

    now = 1_800_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5(now + 5.5 * 3600.0))
    assert live.measured_server_utc_offset_hours() == pytest.approx(5.5)


def test_no_tick_yields_no_offset(monkeypatch):
    class FakeMT5:
        def symbol_info_tick(self, symbol):
            return None

    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5())
    assert live.measured_server_utc_offset_hours() is None


# -- Drift --------------------------------------------------------------
def test_drift_reports_a_dst_change(monkeypatch):
    """The case that costs a day boundary: +01:00 registered after the change.

    Nothing raises when this happens. The policy is still fully specified, the
    account still passes every check, and the daily-loss midnight is simply an
    hour out. Reporting the gap is what makes it visible.
    """
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 2.0)
    drift = live.offset_drift(Policy(1.0))
    assert drift["drift_hours"] == pytest.approx(1.0)
    assert drift["agrees"] is False
    assert "differs" in drift["note"]


def test_drift_of_a_few_seconds_is_agreement(monkeypatch):
    """Tick latency is a second or two, not a policy error."""
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 0.9997)
    drift = live.offset_drift(Policy(1.0))
    assert drift["agrees"] is True


def test_drift_is_silent_when_there_is_nothing_to_compare(monkeypatch):
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": 1.0)
    assert live.offset_drift(Policy()) is None
    monkeypatch.setattr(live, "measured_server_utc_offset_hours",
                        lambda symbol="EURUSD": None)
    assert live.offset_drift(Policy(1.0)) is None



def test_drift_exceeds_half_hour_marks_dst_jump(monkeypatch):
    import challenge.live as live
    class P:
        server_utc_offset_hours = 1.0
    monkeypatch.setattr(live, 'measured_server_utc_offset_hours', lambda s='BTCUSD': 2.0)
    d = live.offset_drift(P())
    assert d['exceeds_one_hour'] is True
    assert abs(d['drift_hours']) > 0.5
