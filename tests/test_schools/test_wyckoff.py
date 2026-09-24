"""Wyckoff school: the accumulation event chain is strict and ordered."""
from schools.wyckoff import wyckoff_school
from core.contracts import TradeDirection

from .conftest import mk, steady_uptrend


def accumulation_series():
    """PS -> SC -> AR -> ST -> Spring -> SOS candles inside a tight range.
    Deterministic: med_vol=med(14x100,90,150,160,200,250)=100 and a small
    median range, so the edge thresholds are hit exactly once, in order."""
    quiet = [mk(99.8, 100.0, 99.7, 99.9, volume=100),
             mk(99.9, 100.1, 99.8, 100.0, volume=100),
             mk(100.0, 100.2, 99.9, 100.1, volume=100),
             mk(100.1, 100.3, 100.0, 100.2, volume=100),
             mk(100.2, 100.4, 100.1, 100.3, volume=100),
             mk(100.3, 100.5, 100.2, 100.4, volume=100),
             mk(100.4, 100.6, 100.3, 100.5, volume=100),
             mk(100.5, 100.7, 100.4, 100.6, volume=100)]
    chain = [
        mk(100.6, 101.0, 99.4, 100.4, volume=100),   # PS: new low, low volume
        mk(100.4, 101.2, 97.5, 99.0, volume=250),    # SC: throw, long lower wick
        mk(99.4, 101.0, 99.1, 100.7, volume=160),    # AR: recovery above SC close
        mk(100.2, 100.9, 98.0, 100.3, volume=90),    # ST: low-vol retest
        mk(100.0, 101.2, 96.8, 100.5, volume=150),   # Spring: shakeout below ST
    ]
    quiet2 = [mk(100.6, 100.9, 100.4, 100.7, volume=100)
              for _ in range(6)]
    sos = [mk(100.9, 102.9, 100.5, 102.7, volume=200)]  # SOS: close above range
    return quiet + chain + quiet2 + sos


def test_accumulation_chain_produces_signal():
    candles = accumulation_series()
    ev = wyckoff_school.evaluate(candles, "XAUUSD", now=1.0)

    assert ev.zones, "trading range must be drawn"
    assert ev.suggestions, "complete Spring/SOS chain must propose"
    assert any(s.pattern in ("spring_reversal", "sos_breakout")
               for s in ev.suggestions)
    assert all(s.direction == TradeDirection.LONG for s in ev.suggestions)
    # the chain must appear in the meta ordering
    events = ev.meta.get("events") or []
    assert events, "must record which Wyckoff events fired"


def distribution_series():
    """PSY -> BC -> AR -> UTAD inside a tight range near 500.
    Mirrors accumulation_series: med_vol=100, med_range=0.6, so the
    distribution thresholds are hit exactly once, in order."""
    quiet = [mk(500.0 + i * 0.05, 500.3, 499.7, 500.2 + i * 0.05,
                volume=100) for i in range(8)]
    chain = [
        mk(500.4, 502.8, 500.0, 500.7, volume=200),    # PSY: supply at the top
        mk(502.4, 505.4, 502.0, 503.0, volume=300),    # BC: buying climax
        mk(503.0, 503.5, 501.5, 501.5, volume=90),     # AR: auto reaction
        mk(501.8, 505.8, 501.6, 502.8, volume=160),    # UTAD: upthrust, close back in
    ]
    quiet2 = [mk(502.5, 503.2, 502.0, 502.7, volume=100) for _ in range(8)]
    return quiet + chain + quiet2


def test_distribution_chain_produces_short_signal():
    candles = distribution_series()
    ev = wyckoff_school.evaluate(candles, "XAUUSD", now=1.0)

    assert ev.zones, "trading range must be drawn"
    dist = ev.meta.get("distribution_events") or []
    assert "UTAD" in dist, "upthrust must be labelled in order"
    suggs = [s for s in ev.suggestions if s.pattern == "utad_reversal"]
    assert suggs, "complete distribution chain must propose a UTAD short"
    assert all(s.direction == TradeDirection.SHORT for s in suggs)
    for s in suggs:
        assert s.stop_loss > s.entry_zone[1], "stop must sit above the entry"
        assert s.take_profit[0] < s.entry_zone[1], "target must be below the shockout"


def test_accumulation_never_fires_on_distribution_series():
    ev = wyckoff_school.evaluate(distribution_series(), "XAUUSD", now=1.0)
    assert not any(s.pattern == "spring_reversal" for s in ev.suggestions)


def test_no_range_means_no_finalized_signal():
    ev = wyckoff_school.evaluate(steady_uptrend(), "XAUUSD", now=1.0)
    assert ev.suggestions == []
    assert ev.meta.get("stage") in ("no_range", None)


def test_out_of_order_events_yield_nothing():
    # reversed chain: SOS before Spring - must not produce a trade
    candles = list(reversed(accumulation_series()))
    ev = wyckoff_school.evaluate(candles, "XAUUSD", now=1.0)
    # even if some events fire, the tradeable signal must respect order
    assert ev.suggestions == []
