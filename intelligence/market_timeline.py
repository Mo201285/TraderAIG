"""MARKET TIMELINE — a chronological, read-only narrative of price structure.

Turns a candle window into an ordered list of structural *events* so the chart
can explain how price arrived where it is, moment by moment, instead of showing
an inert candle series:

    sweep (liquidity raid) -> displacement (impulse) -> FVG (imbalance)
    -> retrace (return into the imbalance)

This module is intentionally:

* **Pure** — no I/O, no clock, no DB. The same candles always yield the same
  events, so the timeline is reproducible and testable.
* **Read-only** — it is an *observability* layer over the candles already
  served by `MarketPlane`. It takes no decision, holds no state, and grants the
  UI no authority; it only narrates what the data shows.
* **Bilingual** — every event carries an English and an Arabic description, in
  the same house style as `MarketContext.market_story`.

The primitives live in `intelligence.smc` (swings, FVGs, order blocks) and are
reused rather than reinvented; the added value here is *time ordering* and the
sweep/displacement/replace vocabulary a trader reads left-to-right.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from core.contracts import Candle, TradeDirection
from core.logging import get_logger
from intelligence.smc import _find_fvgs

log = get_logger("intelligence.market_timeline")

# Tunables. Kept as module constants so the API and its tests share one source
# of truth and cannot silently drift apart.
SWEEP_LOOKBACK = 20          # bars that define the range a sweep must take out
DISPLACEMENT_ATR_MULT = 1.5  # range must exceed this * ATR to count as impulse
DISPLACEMENT_BODY_RATIO = 0.5  # ...and the body must dominate the range
ATR_PERIOD = 14
MAX_EVENTS = 60              # most-recent events returned (keeps payload < ~20KB)

_TYPE_ORDER = {"sweep": 0, "displacement": 1, "fvg": 2, "retrace": 3}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atr_series(candles: Sequence[Candle], period: int = ATR_PERIOD) -> List[Optional[float]]:
    """Average True Range aligned to `candles`; `None` until the window warms."""
    out: List[Optional[float]] = []
    trs: List[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            tr = c.high - c.low
        else:
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
        if i + 1 < period:
            out.append(None)
        else:
            window = trs[i + 1 - period:i + 1]
            out.append(sum(window) / period)
    return out


def _event(kind: str, side: str, time: float, price: float, index: int,
           text_en: str, text_ar: str) -> Dict:
    return {
        "id": f"{kind}-{index}",
        "type": kind,
        "side": side,            # "buy" | "sell" | "neutral"
        "time": time,
        "price": round(float(price), 6),
        "index": index,
        "text_en": text_en,
        "text_ar": text_ar,
    }


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _detect_sweeps(candles: Sequence[Candle], start: int) -> List[Dict]:
    events: List[Dict] = []
    n = len(candles)
    for i in range(max(SWEEP_LOOKBACK, start), n):
        window = candles[i - SWEEP_LOOKBACK:i]
        if not window:
            continue
        hi = max(c.high for c in window)
        lo = min(c.low for c in window)
        c = candles[i]
        # Buyside liquidity taken then rejected => bearish intent (side=sell).
        if c.high > hi and c.close < hi:
            events.append(_event(
                "sweep", "sell", c.time, hi, i,
                f"Buyside liquidity swept above {hi:.3f}; price could not hold",
                f"كشط سيولة الشراء فوق {hi:.3f}؛ السعر لم يثبت فوقها"))
        # Sellside liquidity taken then reclaimed => bullish intent (side=buy).
        if c.low < lo and c.close > lo:
            events.append(_event(
                "sweep", "buy", c.time, lo, i,
                f"Sellside liquidity swept below {lo:.3f}; price reclaimed it",
                f"كشط سيولة البيع تحت {lo:.3f}؛ السعر استعادها"))
    return events


def _detect_displacements(candles: Sequence[Candle], atr: Sequence[Optional[float]],
                          start: int) -> List[Dict]:
    events: List[Dict] = []
    for i in range(start, len(candles)):
        c = candles[i]
        a = atr[i]
        if not a or c.range <= 0:
            continue
        if c.range >= DISPLACEMENT_ATR_MULT * a and c.body >= DISPLACEMENT_BODY_RATIO * c.range:
            side = "buy" if c.is_bullish else "sell"
            verb_en = "up" if side == "buy" else "down"
            verb_ar = "صعودًا" if side == "buy" else "هبوطًا"
            events.append(_event(
                "displacement", side, c.time, c.close, i,
                f"Displacement candle {verb_en} ({c.range / a:.1f}x ATR) — impulse leg",
                f"شمعة إزاحة {verb_ar} ({c.range / a:.1f}× ATR) — دفع سعري"))
    return events


def _fvg_events(fvgs: Sequence) -> List[Dict]:
    events: List[Dict] = []
    for f in fvgs:
        side = "buy" if f.direction == TradeDirection.LONG else "sell"
        mid = (f.top + f.bottom) / 2
        kind_en = "Bullish" if side == "buy" else "Bearish"
        kind_ar = "صاعدة" if side == "buy" else "هابطة"
        events.append(_event(
            "fvg", side, f.time, mid, f.index,
            f"{kind_en} imbalance (FVG) {f.bottom:.3f}–{f.top:.3f} left unfilled",
            f"فجوة قيمة عادلة {kind_ar} {f.bottom:.3f}–{f.top:.3f} غير مُغطّاة"))
    return events


def _detect_retraces(candles: Sequence[Candle], fvgs: List[Dict]) -> List[Dict]:
    """First bar after each FVG that trades back into the gap's near edge."""
    events: List[Dict] = []
    n = len(candles)
    for f in fvgs:
        side = f["side"]
        zone = f.get("_zone")
        if not zone:
            continue
        top, bottom = zone
        for k in range(f["index"] + 1, n):
            c = candles[k]
            if side == "buy" and c.low <= top:
                events.append(_event(
                    "retrace", "buy", c.time, top, k,
                    f"Retrace into bullish imbalance at {top:.3f} — reaction zone",
                    f"ارتداد داخل الفجوة الصاعدة عند {top:.3f} — منطقة تفاعل"))
                break
            if side == "sell" and c.high >= bottom:
                events.append(_event(
                    "retrace", "sell", c.time, bottom, k,
                    f"Retrace into bearish imbalance at {bottom:.3f} — reaction zone",
                    f"ارتداد داخل الفجوة الهابطة عند {bottom:.3f} — منطقة تفاعل"))
                break
    return events


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_timeline(candles: Sequence[Candle], symbol: str = "XAUUSD",
                   timeframe: str = "M5", *,
                   lookback: int = 300,
                   max_events: int = MAX_EVENTS) -> List[Dict]:
    """Return the structural event timeline for `candles`, oldest first.

    `lookback` bounds how far back detections reach (the plane already caps the
    window); `max_events` trims to the most recent events so the payload stays
    small. Returns ``[]`` for a window too short to say anything honest about.
    """
    if len(candles) < 5:
        return []

    lookback = max(5, int(lookback))
    start = max(SWEEP_LOOKBACK, len(candles) - lookback)
    atr = _atr_series(candles)

    events: List[Dict] = []
    events.extend(_detect_sweeps(candles, start))
    events.extend(_detect_displacements(candles, atr, start))

    # Compute FVGs once so retrace detection reuses the exact same zones.
    fvgs = _find_fvgs(candles, lookback=lookback)
    fvg_events = _fvg_events(fvgs)
    for ev, f in zip(fvg_events, fvgs):
        ev["_zone"] = (f.top, f.bottom)
    events.extend(_detect_retraces(candles, fvg_events))
    events.extend(fvg_events)

    # Chronological order; ties broken by structural reading order.
    events.sort(key=lambda e: (e["time"], _TYPE_ORDER.get(e["type"], 9), e["index"]))

    # Drop the internal-only key and keep the most recent slice.
    for ev in events:
        ev.pop("_zone", None)
    if max_events and len(events) > max_events:
        events = events[-max_events:]

    log.debug(f"{symbol} {timeframe}: timeline events={len(events)} "
              f"over {len(candles)} candles")
    return events
