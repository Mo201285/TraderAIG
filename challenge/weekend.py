"""Per-symbol weekend handling: the close window and the reduced-risk window.

Two rules that look similar and are not:

  * a **close window**, where the symbol may not be traded at all -- forex, gold
    and indices stop two hours before their own Friday close, because holding
    them into a weekend means holding them through a gap nobody priced;
  * a **reduced-risk window**, where the symbol may be traded but at half the
    usual risk -- crypto trades 24/7, so it never closes, and what it does have
    is a weekend gap that a normal-sized position cannot absorb.

Both windows are anchored to a per-symbol Friday close read from MT5, and both
fail closed when that close cannot be established. That failure mode is the
single most important decision in this module, so it is stated once, here,
rather than re-derived at each use:

    "Cannot read the close" is treated as "the close has already happened".

The obvious alternative -- treat an unreadable close as "no window, carry on
normally" -- is a fail-OPEN reading of a rule whose entire purpose is to be
conservative about an unpriced gap. It would also be silently permissive in the
one situation where the engine is least able to help: a brand-new symbol it has
never seen would trade at full size through every weekend, which is precisely
the outcome the rule exists to prevent.

`SymbolSchedule` carries a *measurement* of the weekend boundaries, not a
schedule lookup, and the difference matters. python-MT5's `SymbolInfo` exposes
`session_open` and `session_close`, but those are the OPENING and CLOSING PRICES
for the session -- there is no per-symbol trading-hours API in the Python binding.
MQL5 has `SymbolInfoSessionTrade`; Python does not. So the boundary is read from
the terminal rather than derived here: `challenge/mt5_sessions.py` consumes the
schedule the EA publishes (`<Common>\\Files\\sessions\\sessions.json`) and turns
each symbol's weekly sessions into concrete epochs against the policy's
`server_utc_offset_hours`.

A measurement taken from observed last ticks remains usable as a fallback and is
one week stale, which cuts the safe way here: if last week's close was earlier
than this week's will be, the window opens early and the symbol is restricted for
longer than needed. If it was later, the window opens late -- the permissive
direction, and the reason `_observed_close` refuses a close it cannot vouch for
rather than extrapolating one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from core.logging import get_logger

log = get_logger("challenge.weekend")

# Classes whose weekend exposure is a close, not a smaller position. Gold and the
# majors gap on the weekend; crypto does not close, so it is handled by risk
# instead. Named as sets rather than matched by substring because a substring
# rule cannot tell XAUUSD from a crypto pair whose ticker happens to contain
# "AU", and a symbol whose class cannot be decided is closed.
_WEEKEND_CLOSE_CLASSES: FrozenSet[str] = frozenset({"forex", "metal", "index"})
_WEEKEND_RISK_CLASSES: FrozenSet[str] = frozenset({"crypto"})

# How far from `observed_at` a reported boundary may sit and still be believed.
# See `_observed_close`: a week is far enough to catch a clock or data fault and
# close enough to leave a real schedule alone.
_MAX_BOUNDARY_SPAN = 7 * 86400.0

# Suffix -> class. Explicit, because inference is what this module exists to
# avoid. A symbol matching nothing is UNKNOWN, which is closed, not allowed.
_SYMBOL_SUFFIXES: Dict[str, str] = {
    "USD": "forex", "EUR": "forex", "GBP": "forex", "JPY": "forex",
    "CHF": "forex", "AUD": "forex", "NZD": "forex", "CAD": "forex",
    "XAU": "metal", "XAG": "metal",
    "US30": "index", "NAS": "index", "SPX": "index", "UK100": "index",
    "DE40": "index", "JPN": "index", "USTEC": "index",
    "BTC": "crypto", "ETH": "crypto", "LTC": "crypto", "XRP": "crypto",
}

UNKNOWN = "unknown"


def classify(symbol: Optional[str]) -> str:
    """The asset class of a symbol, or UNKNOWN.

    Longest match wins, so `BTCUSD` classifies as `crypto` from its `BTC` prefix
    rather than being read as the `USD` forex pattern that also ends it. A plain
    "ends with USD therefore forex" rule gets every crypto pair exactly wrong,
    which is the failure this ordering exists to prevent.
    """
    if not symbol:
        return UNKNOWN
    upper = symbol.strip().upper()
    best: Optional[str] = None
    best_len = 0
    for suffix, cls in _SYMBOL_SUFFIXES.items():
        if upper.startswith(suffix) and len(suffix) > best_len:
            best, best_len = cls, len(suffix)
    return best or UNKNOWN


@dataclass(frozen=True)
class SymbolSchedule:
    """One symbol's weekend boundaries, in epoch seconds, plus its provenance.

    `observed_close` is the Friday session close. `next_open` is when the symbol
    next starts trading after it, and it is what bounds the reduced-risk window.
    Without it the reduction has no end: a `now >= close - lead` test with no
    upper bound reads "inside the window" forever, so a Monday reading of a
    schedule captured on the previous Friday would still be halved. The close
    classes get away without this because their window ends at the close itself,
    which is why the omission is easy to miss while only crypto is affected.
    """

    symbol: str
    observed_close: float
    observed_at: float
    next_open: Optional[float] = None

    def as_dict(self) -> Dict[str, object]:
        return {"symbol": self.symbol, "observed_close": self.observed_close,
                "observed_at": self.observed_at, "next_open": self.next_open}


def _observed_close(schedules: Dict[str, SymbolSchedule],
                    symbol: str) -> Optional[SymbolSchedule]:
    """This symbol's close, or None when it cannot be established.

    None is the answer for an unseen symbol, a None value, or a close so far from
    now that it cannot be a weekend boundary -- which is a clock or data fault
    rather than a schedule.

    The tolerance is deliberately a WEEK rather than "not in the future". A
    schedule read from the terminal is forward-looking by nature: read at 23:00
    on Friday, the close it reports for 23:59:59 that night is an hour in the
    future and completely legitimate. Banning any future close would refuse
    almost every schedule the reader produces, and the fail-closed path it would
    fall into would look like the rule working. What actually matters is the
    far end: a close placed days away moves the window out of reach, so
    `now < close - lead` holds for ever and the symbol is never restricted --
    silently fail-OPEN. A week either way is inside that fault's range and
    outside a real schedule's.
    """
    entry = schedules.get(symbol.upper())
    if entry is None or entry.observed_close <= 0.0:
        return None
    span = abs(entry.observed_close - entry.observed_at)
    if span > _MAX_BOUNDARY_SPAN:
        return None
    return entry


def _close_unreadable_note(schedules: Dict[str, SymbolSchedule],
                           symbol: str) -> str:
    """WHY this symbol's close could not be placed, in one short clause.

    `_observed_close` returns the same None for three different faults, and the
    action each calls for is not the same: an empty mapping means the terminal
    never published the schedule at all (fix the EA / the shared-files path -- it
    affects every symbol, not this one), whereas a populated mapping that lacks
    the symbol is a per-symbol gap, and a close too far from its reading is a
    clock or data fault. An operator reading only "could not be read" cannot tell
    a deployment-wide feed failure from one symbol the EA did not cover, so this
    names the cause without changing the fail-closed verdict.
    """
    if not schedules:
        return ("no session schedule has been published by the terminal, so no "
                "Friday close is available for any symbol")
    entry = schedules.get(symbol.upper())
    if entry is None or entry.observed_close <= 0.0:
        return ("the symbol is absent from the published session schedule (the "
                "terminal reported no usable Friday session for it)")
    span = abs(entry.observed_close - entry.observed_at)
    if span > _MAX_BOUNDARY_SPAN:
        return (f"the published close sits {span / 86400.0:.1f} days from its "
                f"reading, too far to be a weekend boundary (a clock or data "
                f"fault, not a schedule)")
    return "the Friday close could not be established"


def _server_epoch(epoch: float, offset_hours: float) -> float:
    """Shift an epoch into the broker's frame, for weekday arithmetic only.

    Only the weekday is read back out of this, so no timezone library is needed
    and no DST claim is made -- `server_utc_offset_hours` is the offset the
    policy states, and a broker that moves it is a broker whose offset needs
    re-registering.
    """
    return epoch + float(offset_hours or 0.0) * 3600.0


def in_close_window(policy, epoch: float, symbol: str,
                    schedules: Dict[str, SymbolSchedule]) -> Tuple[bool, str]:
    """Whether `symbol` is inside its own weekend close window, and why.

    Returns `(closed, reason)`. The reason is always populated, including on the
    permissive side, because "why was this allowed to trade" is the question an
    operator asks first when a position goes wrong.
    """
    cls = classify(symbol)
    if cls == UNKNOWN:
        # Fail closed on an unclassified symbol: the class decides whether this
        # is a close or a half-size rule, and not knowing which means not knowing
        # whether the symbol may be traded at all.
        return True, (f"{symbol}: asset class unknown, so its weekend rule is "
                      f"unknown; closed until the class is established")
    if cls not in _WEEKEND_CLOSE_CLASSES:
        return False, (f"{symbol}: {cls} does not close for the weekend; "
                      f"handled by risk, not by a close window")
    lead_minutes = float(getattr(policy, "weekend_close_lead_minutes", 120) or 0)
    entry = _observed_close(schedules, symbol)
    if entry is None:
        return True, (f"{symbol}: its Friday close could not be read from MT5, "
                      f"so the close window cannot be placed; closed "
                      f"({_close_unreadable_note(schedules, symbol)})")

    offset = float(getattr(policy, "server_utc_offset_hours", 0.0) or 0.0)
    now_server = _server_epoch(epoch, offset)
    close_server = _server_epoch(entry.observed_close, offset)
    window_start = close_server - lead_minutes * 60.0
    # `now` must fall inside the same Friday as the close, and if it does not,
    # the question is moot.
    #
    # This is the check whose absence is the interesting bug. `window_end` is
    # derived from the CLOSE, so a reading taken on the Tuesday before that
    # close -- which is the common case, because the close being examined is last
    # week's observation -- still satisfied `window_start <= now < window_end`
    # whenever the arithmetic happened to land that way, and reported a Tuesday
    # as "inside the weekend close window". The window is about a moment in the
    # future relative to the observation, so "now" has to be on the close's own
    # day for "before the close" to mean anything.
    now_day = dt.datetime.fromtimestamp(now_server // 86400.0 * 86400.0,
                                        dt.timezone.utc)
    close_day = dt.datetime.fromtimestamp(close_server // 86400.0 * 86400.0,
                                          dt.timezone.utc)
    if close_day.weekday() != 4:
        # The observation is not on a Friday. Refuse rather than guess a weekday:
        # a window anchored to the wrong day is either always open or never open,
        # and both are worse than saying so.
        return True, (f"{symbol}: observed close is not a Friday, so the "
                      f"weekend window cannot be placed; closed")
    # The window is `[close - lead, close]`: trading stops *before* the close,
    # and it is open again once the close has passed. A window that extended
    # past the close would be reporting a symbol as closed after it had already
    # shut, which would leave every Friday-night reopen unreachable -- and the
    # reason this bug is easy to write is that "close window" sounds like it
    # should span the closure rather than the run-up to it.
    #
    # `now` is allowed to be on the following day as well: a symbol closing at
    # 23:00 Friday server time is still closed at 01:00 Saturday, and refusing
    # that would reopen gold for the hour it is genuinely unavailable.
    delta_days = (now_day.date() - close_day.date()).days
    if delta_days not in (0, 1):
        return False, (f"{symbol}: not on the weekend of its observed close "
                       f"(now {now_day:%a %Y-%m-%d}, close "
                       f"{close_day:%a %Y-%m-%d}); outside the close window")
    window_end = close_server

    if not (window_start <= now_server < window_end):
        return False, (f"{symbol}: outside the close window (opens "
                       f"{lead_minutes:.0f} min before its Friday close at "
                       f"{entry.observed_close:.0f})")
    return True, (f"{symbol}: inside the weekend close window "
                  f"({lead_minutes:.0f} min before its Friday close at "
                  f"{entry.observed_close:.0f}, observed "
                  f"{entry.observed_at:.0f})")


def risk_multiplier(policy, epoch: float, symbol: str,
                    schedules: Dict[str, SymbolSchedule]) -> Tuple[float, str]:
    """The weekend risk multiplier for `symbol`: 1.0 normally, less inside.

    Fraction of the *usual* risk, not of lots. A lot multiplier would need a
    per-symbol contract size and a pip value to be equivalent, and would be
    wrong for any symbol where those differ from the account's default; risk is
    what the rule is about and what the governor already sizes in.
    """
    multiplier = float(getattr(policy, "weekend_risk_multiplier", 1.0) or 1.0)
    if multiplier >= 1.0:
        return 1.0, f"{symbol}: no weekend risk reduction in force"
    cls = classify(symbol)
    if cls == UNKNOWN:
        # Fail closed, matching `in_close_window`. An unclassified symbol cannot
        # be shown to be outside the risk window either, and returning 1.0 here
        # would mean the same symbol is closed by one rule and unrestricted by
        # the other -- two answers to one question, differing only by which
        # function was asked.
        return multiplier, (f"{symbol}: asset class unknown, so it cannot be "
                            f"shown to be outside the window; risk capped at "
                            f"{multiplier:.0%}")
    if cls not in _WEEKEND_RISK_CLASSES:
        return 1.0, (f"{symbol}: {cls} is not a weekend-risk class; no "
                     f"reduction applied")
    entry = _observed_close(schedules, symbol)
    if entry is None:
        # Fail closed: a symbol we cannot place inside or outside a window is not
        # one to trade at full size through a weekend gap.
        return multiplier, (f"{symbol}: Friday close unreadable, so the window "
                            f"cannot be placed; reduced to the restricted size "
                            f"({_close_unreadable_note(schedules, symbol)})")
    offset = float(getattr(policy, "server_utc_offset_hours", 0.0) or 0.0)
    now_server = _server_epoch(epoch, offset)
    close_server = _server_epoch(entry.observed_close, offset)
    lead_minutes = float(getattr(policy, "weekend_close_lead_minutes", 120) or 0)
    if now_server < close_server - lead_minutes * 60.0:
        return 1.0, f"{symbol}: outside the weekend risk window"
    # The window ends when the symbol reopens, not at some later reading of the
    # same schedule. Without this bound a Monday check against a Friday capture
    # still satisfies `now >= close - lead` and halves the position all week --
    # a permanent handicap that looks like the rule working.
    if entry.next_open is not None and now_server >= _server_epoch(
            entry.next_open, offset):
        return 1.0, (f"{symbol}: reopened at {entry.next_open:.0f}; the weekend "
                     f"risk window has passed")
    # Inside the window from here on, including the weekend itself, where the
    # close has passed and the gap is what is left.
    return multiplier, (f"{symbol}: inside the weekend risk window; risk "
                        f"capped at {multiplier:.0%} of usual")


def symbols_needing_reduction(policy, epoch: float,
                              symbols: List[str],
                              schedules: Dict[str, SymbolSchedule],
                              current_risk: Dict[str, float],
                              usual_risk: Optional[Dict[str, float]] = None
                              ) -> List[Dict[str, object]]:
    """Symbols held at more risk than the weekend rule now allows.

    Option (b)+(c) from the operator: shrink what is already open, and cap what
    is new. `current_risk` is each held symbol's present risk in account
    currency, and `usual_risk` is the risk that symbol would normally be sized
    to.

    The ceiling is `usual * multiplier`, NOT `current * multiplier`. The
    distinction is the whole function: a position sized at the normal figure
    before the window opened is compliant the moment it is *already* at the
    reduced size, whereas `current * mult` would ask it to halve again every
    time the function ran. That version compounds -- Saturday would demand a
    quarter, Sunday a sixteenth -- and an instruction that cannot be satisfied by
    waiting is one the operator learns to ignore.

    `usual_risk` is required per symbol rather than inferred from what is held,
    because inferring it makes the rule unfalsifiable: any position would be
    "already correct" by construction. Where it is not supplied the symbol is
    reported as unverifiable rather than as compliant.
    """
    out: List[Dict[str, object]] = []
    for symbol in symbols:
        mult, why = risk_multiplier(policy, epoch, symbol, schedules)
        held = float(current_risk.get(symbol, 0.0) or 0.0)
        if mult >= 1.0 or held <= 0.0:
            continue
        usual = None if usual_risk is None else usual_risk.get(symbol)
        if usual is None:
            out.append({"symbol": symbol, "current_risk": held,
                        "allowed_risk": None, "excess": None,
                        "needs_trim": True,
                        "reason": why + "; normal size for this symbol is not "
                                         "recorded, so compliance cannot be shown"})
            continue
        allowed = float(usual) * mult
        out.append({"symbol": symbol, "current_risk": held,
                    "allowed_risk": allowed,
                    "excess": max(0.0, held - allowed),
                    "needs_trim": held > allowed,
                    "reason": why})
    return out


def window_report(policy, epoch: float, symbols: List[str],
                  schedules: Dict[str, SymbolSchedule]) -> Dict[str, object]:
    """Every symbol's weekend verdict, for the dashboard and the API."""
    rows: List[Dict[str, object]] = []
    for symbol in symbols:
        closed, why = in_close_window(policy, epoch, symbol, schedules)
        mult, mwhy = risk_multiplier(policy, epoch, symbol, schedules)
        rows.append({"symbol": symbol, "asset_class": classify(symbol),
                     "closed": closed, "risk_multiplier": mult,
                     "close_reason": why, "risk_reason": mwhy})
    return {"epoch": epoch, "symbols": rows,
            "scheduled": sorted(schedules)}


def known_classes() -> Set[str]:
    return set(_SYMBOL_SUFFIXES.values()) | {UNKNOWN}
