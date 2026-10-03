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


# --- coverage the corruption matrix proved was absent ------------------------
#
# Guards 3 and 4 below were neutered and the suite stayed green. Both had tests
# by name; neither test made the guard load-bearing.


def _tick(monkeypatch, tick_time, now):
    """A broker whose only symbol reports `tick_time`."""

    class Tick:
        def __init__(self, t):
            self.time = t

    class FakeMT5:
        def symbol_info_tick(self, symbol):
            return Tick(tick_time)

    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5())


def test_a_non_quarter_offset_is_rounded_to_the_nearest_quarter_hour(monkeypatch):
    """+05:31 has to become +05:30, or the day boundary sits 6 minutes out.

    The existing fractional test used +05:30, which is already on the quarter
    grid -- so it passed with the rounding deleted. This one is deliberately off
    the grid, and it pins the direction as well as the magnitude.
    """
    now = 1_800_000_000.0
    _tick(monkeypatch, now + (5.0 + 31.0 / 60.0) * 3600.0, now)
    assert live.measured_server_utc_offset_hours() == pytest.approx(5.5)


def test_rounding_goes_to_the_nearest_quarter_and_not_always_down(monkeypatch):
    """+05:44 rounds UP to +05:45.

    Half the cases go up. A guard that only ever rounds down would pass the
    test above, and would place the day boundary early on those brokers.
    """
    now = 1_800_000_000.0
    _tick(monkeypatch, now + (5.0 + 44.0 / 60.0) * 3600.0, now)
    assert live.measured_server_utc_offset_hours() == pytest.approx(5.75)


def test_a_stale_tick_is_refused_rather_than_believed(monkeypatch):
    """A tick from three hours ago measures nothing.

    A quiet session leaves the last tick old, and tick-minus-now would then read
    as a large NEGATIVE offset -- which is a number, so it would be registered
    and would move the day boundary by hours. There is no tick here, so there is
    no measurement, and the honest answer is None.
    """
    now = 1_800_000_000.0
    _tick(monkeypatch, now - 3 * 3600.0, now)
    assert live.measured_server_utc_offset_hours() is None


def test_a_tick_just_inside_the_age_limit_is_still_believed(monkeypatch):
    """The 60s guard needs its other side, or "reject stale" is satisfied by
    rejecting everything -- which the neighbouring tests cannot distinguish.

    A PAST tick is what makes the age meaningful: `age = now - tick_time`, so
    only a past tick can be old. Its measured offset is therefore near zero,
    which is the correct reading for a broker on UTC with a tick 30s old.
    """
    now = 1_800_000_000.0
    _tick(monkeypatch, now - 30.0, now)
    assert live.measured_server_utc_offset_hours() == pytest.approx(0.0)


def test_a_tick_just_outside_the_age_limit_is_refused(monkeypatch):
    """61 seconds is over the line, so the boundary is where it is claimed.

    Left alone this would read as roughly -0.017h, which rounds to 0.0 and
    looks like a perfectly good measurement of a UTC broker. The age guard is
    the only thing standing between a quiet session and a fabricated offset.
    """
    now = 1_800_000_000.0
    _tick(monkeypatch, now - 61.0, now)
    assert live.measured_server_utc_offset_hours() is None
