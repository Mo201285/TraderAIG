"""Per-symbol weekend boundaries, read from the terminal's own schedule.

python-MT5 cannot answer "when does EURUSD stop trading on Friday". Its
`SymbolInfo` carries `session_open` and `session_close`, which are the opening
and CLOSING PRICES of the current session, not its times, and the binding has no
trading-hours API at all. So the boundary this module places cannot come from
python-MT5.

MQL5 can: `SymbolInfoSessionTrade` is the terminal's own answer, authoritative
and forward-looking. The EA publishes it to
`<TERMINAL_COMMONDATA_PATH>\\Files\\sessions\\sessions.json` (see
`PublishSessionSchedules` in `mt5/TraderAIG.mq5`), and this module consumes that.

Everything here fails closed. The single decision that matters is what a missing
schedule means, and it is the same one `challenge/weekend.py` already states:
an unreadable close is treated as a close that has happened. This module's
contribution to that is simply to return no entry rather than a guess, so the
caller's existing refusal does the work -- there is deliberately no "assume
Friday 22:00 server time" fallback, because such a default would be a guess
about an unpriced gap wearing the authority of a measurement.

The published shape, written by hand in MQL5 because `Json.mqh` there supports
no nested objects or arrays:

    {"server_time": 1790971200,
     "symbols": {"EURUSD": {"symbol": "EURUSD", "mode": 4,
                            "sessions": [[5, 50400, 82800], [6, 0, 600]]}}}

`mode` is `SYMBOL_TRADE_MODE` and `sessions` entries are
`[weekday, from_seconds, to_seconds]` in the terminal's own -- broker -- day,
where weekday is MQL5's `ENUM_DAY_OF_WEEK` (Sunday = 0, Friday = 5).

Offsets are read from the document's own `server_time`, not from the policy, when
one is present: the document is stamped by the terminal that produced it, so it
is the more authoritative statement of which day "86400" refers to. The policy's
`server_utc_offset_hours` remains the authority for the arithmetic the caller
does with the result.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.logging import get_logger

from .weekend import SymbolSchedule

log = get_logger("challenge.mt5_sessions")

# MQL5 ENUM_DAY_OF_WEEK.
FRIDAY = 5
SUNDAY = 0
MONDAY = 1

# `SYMBOL_TRADE_MODE_DISABLED`. A symbol the terminal reports as disabled is not
# tradeable at all, so placing a weekend window on it would be describing a rule
# that cannot apply.
TRADE_MODE_DISABLED = 0

# `SYMBOL_TRADE_MODE_CLOSE_ONLY` and `SYMBOL_TRADE_MODE_SHORTONLY` both refuse
# new longs; for a weekend close window the practical answer is the same.
TRADE_MODE_CLOSE_ONLY = 3
TRADE_MODE_SHORT_ONLY = 2
TRADE_MODE_LONG_ONLY = 1

# A gap at least this wide is a weekend, not a lunch break. Twelve hours sits
# above every intraday break these venues publish (the longest seen is around
# 90 minutes) and below the shortest weekend: a 24/7 symbol runs Friday 23:59:59
# to Sunday 00:00, which is 24 hours and one second.
MIN_WEEKEND_GAP_SECONDS = 12 * 3600.0

# MT5_COMMON_DATA points at <TERMINAL_COMMONDATA_PATH>\Files, which is what the
# EA writes relative to FILE_COMMON. The default mirrors `InpMarketSubDir`'s
# sibling so both publishers resolve under the same root.
_DEFAULT_SUBDIR = "sessions"
_DEFAULT_FILENAME = "sessions.json"


def sessions_path(common_root: Optional[str] = None,
                  subdir: str = _DEFAULT_SUBDIR) -> Path:
    """Where the EA publishes the schedule, given the shared-files root."""
    root = common_root or os.environ.get("MT5_COMMON_DATA") or ""
    return Path(root) / subdir / _DEFAULT_FILENAME


def _read_document(path: Path) -> Optional[dict]:
    """The published document, or None for any reason it cannot be used.

    Every failure -- absent, unreadable, empty, malformed, not an object -- is
    the same answer. The caller's response to "no schedule" is a closed symbol,
    so distinguishing the causes here would only produce a more confident
    message about a situation where the correct action is identical.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("session schedule unreadable at %s: %s", path, exc)
        return None
    if not raw.strip():
        log.warning("session schedule at %s is empty", path)
        return None
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        log.warning("session schedule at %s is not JSON: %s", path, exc)
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("symbols"), dict):
        log.warning("session schedule at %s has no symbols object", path)
        return None
    return doc


@dataclass(frozen=True)
class BrokerClock:
    """The broker's current day, and the weekday that day actually is.

    Both halves must come from the same shift. Computing the midnight from the
    shifted time but the weekday from the raw epoch gets them out of step
    whenever the offset carries the wall clock across midnight: at UTC+3, 21:00
    UTC is 00:00 the next day, so an instant whose UTC date is the 1st is a
    Friday for the broker while the raw epoch's UTC weekday says Thursday. A
    weekday one day early puts every session of the week in the wrong column and
    lands the weekend boundary a full week out, with no visible error anywhere.
    """

    midnight: float
    weekday: int
    server_now: float


def _broker_clock(server_now: float, offset_hours: float) -> BrokerClock:
    offset = float(offset_hours or 0.0) * 3600.0
    shifted = float(server_now) + offset
    midnight = (shifted // 86400.0) * 86400.0 - offset
    # The weekday is read back off the SHIFTED time, which is the broker's own
    # wall clock, never off `midnight` whose UTC date may be the previous day.
    return BrokerClock(midnight=midnight,
                       weekday=int((shifted // 86400.0 + 4) % 7),
                       server_now=float(server_now))


def _weekday(epoch: float) -> int:
    """MQL5 weekday index (Sunday = 0) for a broker wall-clock instant."""
    # 1970-01-01 was a Thursday (MQL5 index 4), so this is an index, not a
    # name: derived once, never guessed per call.
    return int((epoch // 86400.0 + 4) % 7)


def _seconds(entry: object) -> Optional[Tuple[int, int]]:
    """`[weekday, from, to]` as a validated triple, or None if unusable."""
    if not isinstance(entry, (list, tuple)) or len(entry) != 3:
        return None
    try:
        day = int(entry[0])
        start = int(entry[1])
        end = int(entry[2])
    except (TypeError, ValueError):
        return None
    if not 0 <= day <= 6:
        return None
    # A session ending before it starts is not a zero-length session, it is a
    # malformed one, and accepting it would place an open that precedes a close
    # and invert the window.
    if start < 0 or end > 86400 or end <= start:
        return None
    return day, start, end


def _ordered_sessions(clock: BrokerClock,
                      sessions: List[Tuple[int, int, int]],
                      weeks: int = 1) -> List[Tuple[int, float, float]]:
    """`(day, start, end)` epochs for the coming broker week(s), in order.

    Days are placed by wrapping forward from the broker's current day, so a
    Saturday reading puts Sunday's sessions a day ahead rather than five behind.
    `weeks=2` also reaches BACK one week, which is the only way the Friday that
    is being closed can be seen from a reading taken on the Saturday after it --
    a Saturday reading finds no Friday at all in the coming week, and a boundary
    that disappears on the one day the weekend is still running is a rule that
    stops working exactly when it is needed.
    """
    out: List[Tuple[int, float, float]] = []
    for day, start, end in sessions:
        ahead = (day - clock.weekday) % 7
        for k in range(-(weeks - 1), weeks):
            base = clock.midnight + float(ahead + 7 * k) * 86400.0
            out.append((day, base + float(start), base + float(end)))
    out.sort(key=lambda item: (item[1], item[2]))
    return out


def _weekend_boundaries(clock: BrokerClock,
                        sessions: List[Tuple[int, int, int]]
                        ) -> Tuple[Optional[float], Optional[float]]:
    """The week's close and the next open after it, in epoch seconds.

    Anchored on the first GAP between consecutive sessions wide enough to be a
    weekend, not on "the last session of the week". That is what lets one
    algorithm serve both kinds of symbol:

      * a real Friday-close symbol has a visible gap, often behind a small
        Saturday spillover, and that gap is exactly the weekend;
      * a 24/7 crypto symbol has NO gap at all -- Friday's session runs straight
        into Saturday's -- so a gap search finds nothing and the calendar has to
        supply the boundary. Anchoring on "the last session of the week" would
        put crypto's close at Saturday 23:59:59 and its risk reduction a full day
        late: the weekend after the one it exists to cover.

    The calendar path pairs the reopen with the Friday that ENDS BEFORE it, and
    not with the last Friday in the window. On a Saturday the coming week
    contains next Friday and this coming Sunday, so pairing the two would hand
    back a window that ends before it starts -- and a window with its ends
    swapped is not a conservative reading, it is a rule that reduces nothing
    during the weekend it was written for.
    """
    this_week = _ordered_sessions(clock, sessions)
    for (_day_a, _start_a, end_a), (_day_b, start_b, _end_b) in zip(
            this_week, this_week[1:]):
        if start_b - end_a >= MIN_WEEKEND_GAP_SECONDS:
            return end_a, start_b

    # No gap anywhere: anchor on the calendar, reaching back a week so the
    # elapsed part of this weekend is in view.
    return _calendar_boundaries(clock, _ordered_sessions(clock, sessions, weeks=2))


def _calendar_boundaries(clock: BrokerClock,
                         ordered: List[Tuple[int, float, float]]
                         ) -> Tuple[Optional[float], Optional[float]]:
    """Reopen first, then the last Friday that ends before it."""
    reopen = None
    for day, start, _end in ordered:
        if day in (SUNDAY, MONDAY) and start >= clock.server_now:
            reopen = start
            break
    if reopen is None:
        log.warning("no weekend gap and no Sunday/Monday session still ahead "
                    "in %d sessions", len(ordered))
        return None, None

    friday = None
    for day, _start, end in ordered:
        if day == FRIDAY and end < reopen:
            friday = end
    if friday is None:
        log.warning("no Friday session ends before the reopen at %d", reopen)
        return None, None
    return friday, reopen


def schedules_from_document(doc: dict, offset_hours: float,
                            now: Optional[float] = None) -> Dict[str, SymbolSchedule]:
    """Turn one published document into per-symbol weekend boundaries.

    A symbol present in the document but reporting no usable session yields no
    entry, exactly as an absent symbol does. The published `mode` is honoured
    where it exists: a disabled symbol is skipped rather than given a window,
    because the terminal is telling us the rule cannot apply to it.
    """
    symbols = doc.get("symbols")
    if not isinstance(symbols, dict):
        return {}

    server_now = doc.get("server_time")
    if not isinstance(server_now, (int, float)) or server_now <= 0:
        server_now = float(now) if now is not None else 0.0
    server_now = float(server_now)

    clock = _broker_clock(server_now, offset_hours)

    out: Dict[str, SymbolSchedule] = {}
    for name, entry in symbols.items():
        if not isinstance(entry, dict):
            continue
        mode = entry.get("mode")
        if isinstance(mode, int) and mode == TRADE_MODE_DISABLED:
            continue
        raw_sessions = entry.get("sessions")
        if not isinstance(raw_sessions, list):
            continue
        parsed = [s for s in (_seconds(item) for item in raw_sessions)
                  if s is not None]
        if not parsed:
            continue
        last_close, next_open = _weekend_boundaries(clock, parsed)
        if last_close is None:
            continue
        symbol = str(entry.get("symbol") or name).upper()
        out[symbol] = SymbolSchedule(symbol=symbol,
                                     observed_close=last_close,
                                     observed_at=server_now,
                                     next_open=next_open)
    return out


def load_schedules(offset_hours: float, now: float,
                   common_root: Optional[str] = None,
                   subdir: str = _DEFAULT_SUBDIR) -> Dict[str, SymbolSchedule]:
    """Read the terminal's published schedule, or nothing at all.

    Returns an empty mapping when the document is absent, unreadable or
    malformed. That emptiness is the fail-closed signal the weekend rules act
    on; it is deliberately not filled in with a default.
    """
    path = sessions_path(common_root, subdir)
    doc = _read_document(path)
    if doc is None:
        return {}
    return schedules_from_document(doc, offset_hours, now=now)
