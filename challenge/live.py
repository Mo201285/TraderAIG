"""The bridge between the canonical account and the challenge policy layer.

§34.15 puts the challenge verdict on the live decision path, which means the
Risk Governor has to reach the same account, the same policy and the same
headroom figures the dashboard is reading — and it has to reach them without the
dashboard being involved, because §28 makes the UI a surface of the control
plane rather than an authority.

Both callers therefore come through here rather than each re-deriving the
mapping. `operations/api.py` and `risk/governor.py` are both below the control
plane and neither may import the other, so the shared answer lives in the layer
they both depend on.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from core.state import CanonicalState, state

log = get_logger("challenge.live")


def _state(state_ref: Optional[CanonicalState] = None) -> CanonicalState:
    return state_ref if state_ref is not None else state


def connected_account_id(state_ref: Optional[CanonicalState] = None) -> str:
    """The account being graded, identified by the broker login.

    The MT5 login rather than a name or an index, because it is the only
    identifier here that comes from the venue and cannot be reassigned by
    accident. `"unconnected"` rather than an exception when no terminal is
    attached, so a read still answers.

    `state_ref` exists because `RiskGovernor` is constructed with an injected
    `CanonicalState`. A bridge that reached for the module-global instead would
    grade every candidate against whatever the process-global account happens to
    be, which is right in production and wrong in every test that bothers to
    inject a state — and a gate that only works against one global is a gate
    nobody can test.
    """
    login = int(getattr(_state(state_ref).account, "login", 0) or 0)
    return str(login) if login else "unconnected"


def configured_program() -> str:
    """The evaluation program, from configuration only.

    Env-driven rather than inferred from the account. A broker reports a server
    and a currency, never which evaluation the trader signed up for; guessing it
    from the balance would pick a policy for an account the operator never
    described, which is the class of assumption §34.6 forbids.
    """
    return str(os.getenv("TRADERAIG_CHALLENGE_PROGRAM", "") or "")


def configured_provider(account: Any = None) -> str:
    """The prop firm whose terms govern this account.

    Env-driven first, and only then the account's own `broker` field. The two
    are NOT the same name and conflating them is what made this account read as
    unmanaged: MT5 reports `broker` blank on a live login while `server` is
    `FTTrading-Server`, so the firm ("For Traders") had to come from
    configuration and the server had to be passed separately as a SCOPE.

    The distinction is load-bearing. `server` is a filter -- which broker's
    document these terms were read from -- and a provider is who the trader
    signed up with. Passing the server as the provider would look up a firm
    called `FTTrading-Server` and find nothing, which is indistinguishable from
    having no policy at all.

    The value that came back from the environment was not always a firm name.
    A deployment had `TRADERAIG_CHALLENGE_PROVIDER=TRADERAIG_CHALLENGE_PROVIDER`
    -- the variable's own name echoed back as its value -- which "resolved"
    only because the same string had been typed into the policy. That is a
    lookup that agrees with itself and tells the operator nothing about which
    firm's rules are in force, and the registry key read like a mistake. So a
    value that is merely this variable's own name is treated as unset and falls
    through, rather than being accepted as an identity.
    """
    configured = str(os.getenv("TRADERAIG_CHALLENGE_PROVIDER", "") or "").strip()
    if configured and not _is_placeholder_provider(configured):
        return configured
    return str(getattr(account, "broker", "") or "").strip()


#: Values that name no firm: an empty string, or the configuration variable's
#: own name standing in for a value nobody supplied.
_PROVIDER_PLACEHOLDERS = frozenset({"TRADERAIG_CHALLENGE_PROVIDER"})


def _is_placeholder_provider(value: str) -> bool:
    """True when `value` is a placeholder rather than a provider identity."""
    return value.upper() in _PROVIDER_PLACEHOLDERS


def live_policy(state_ref: Optional[CanonicalState] = None):
    """The registered policy for the connected account, or None.

    None means "no policy resolves", which the callers must distinguish from
    "everything is fine". It is the correct state for a deployment that trades
    its own money and has never registered challenge terms.
    """
    account = _state(state_ref).account
    provider = configured_provider(account)
    program = configured_program()
    if not provider or not program:
        return None
    # The server scopes the policy; it never identifies the firm. A tournament
    # written from one broker's document must not decide an account on another,
    # and `resolve` returns nothing rather than inheriting across that gap.
    server = str(getattr(account, "server", "") or "").strip() or None
    try:
        from challenge.service import challenge_service as svc

        return svc.policy_for(provider, program, server=server)
    except Exception:  # noqa: BLE001
        log.exception("challenge policy resolution failed")
        return None


def is_managed(state_ref: Optional[CanonicalState] = None) -> bool:
    """True when a challenge policy actually governs the connected account.

    This is the switch that keeps §34.15 out of ordinary trading: an account with
    no registered policy is not a challenge account, and the gate does not
    pretend otherwise by guessing rules for it.
    """
    return live_policy(state_ref) is not None


def account_inputs(state_ref: Optional[CanonicalState] = None) -> Dict[str, float]:
    """Live equity/balance/margin/open-risk for the canonical account."""
    account = _state(state_ref).account
    open_risk = 0.0
    for position in _state(state_ref).positions.values():
        try:
            open_risk += float(getattr(position, "risk", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            continue
    return {
        "equity": float(getattr(account, "equity", 0.0) or 0.0),
        "balance": float(getattr(account, "balance", 0.0) or 0.0),
        "margin": float(getattr(account, "margin", 0.0) or 0.0),
        "open_risk": open_risk,
    }


def measured_server_utc_offset_hours(
        symbol: str = "BTCUSD") -> Optional[float]:
    """The broker's current UTC offset, read from its own clock, or None.

    Prefers BTCUSD for measurement (requirement 2), falling back to EURUSD/XAUUSD
    if BTCUSD tick is unavailable. MT5 exposes no server time function; every tick
    carries the server's timestamp. Offset = tick.time - host.time (hours).

    Ignore ticks older than 60s (requirement 2). Round to nearest 0.25 hour
    (requirement 2).
    """
    try:
        import MetaTrader5 as mt5  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        import time as _time
    except Exception:  # noqa: BLE001
        return None
    now = _time.time()
    for sym in (symbol or "BTCUSD", "BTCUSD", "EURUSD", "XAUUSD"):
        try:
            tick = mt5.symbol_info_tick(sym)
        except Exception:
            continue
        if tick is None:
            continue
        tick_time = float(getattr(tick, "time", 0.0) or 0.0)
        if tick_time <= 0:
            continue
        age = now - tick_time
        if age < 0:
            age = 0.0  # tick slightly ahead of host (clock skew) is valid
        if age > 60.0:
            continue  # ignore old tick
        offset_h = (tick_time - now) / 3600.0
        q = 0.25
        offset_q = round(offset_h / q) * q
        return round(offset_q, 6)
    return None


def server_utc_offset_hours(policy: Any = None) -> float:
    """The broker's UTC offset in hours, for the daily-loss day boundary.

    Prefers the registered policy value, and falls back to measuring the broker's
    current offset live. The order matters: the policy is the recorded term with
    a source and is what an audit reads, while the live measurement is what keeps
    the day boundary correct across a DST change. When the two disagree the
    policy wins here and `offset_drift` reports the gap, so the correction is
    visible rather than silent in either direction.

    Falls back to 0.0 only for an *unmanaged* account, where no daily limit
    applies and so no day boundary is being claimed. A managed account whose
    policy has no offset is a different case and does not fall back: it goes
    through with 0.0 and `daily_loss_headroom` scores it UNKNOWN, so the
    account is refused on the rule rather than quietly measured against the
    wrong midnight.

    The default is written out rather than defaulted in the signature so that
    reading any call site shows the decision at the point it is made.
    """
    offset = getattr(policy, "server_utc_offset_hours", None)
    if offset is not None:
        return float(offset)
    measured = measured_server_utc_offset_hours()
    return float(measured) if measured is not None else 0.0


def offset_drift(policy: Any = None) -> Optional[Dict[str, Any]]:
    """How far the registered offset has drifted from the broker's live one.

    A DST change makes the recorded value wrong without making it look wrong:
    nothing raises, the policy is still fully specified, and the daily-loss
    midnight is simply somewhere else. Reporting the gap in hours turns that
    into something an operator can see before it costs a day boundary.

    None when there is nothing to compare -- no policy value registered, or no
    live reading available.

    Drift > 1.0 hour is flagged as exceeds_one_hour (requirement 2).
    """
    registered = getattr(policy, "server_utc_offset_hours", None)
    if registered is None:
        return None
    measured = measured_server_utc_offset_hours()
    if measured is None:
        return None
    drift = round(float(measured) - float(registered), 4)
    exceeds_half_hour = abs(drift) > 0.5
    return {"registered_hours": float(registered),
            "measured_hours": float(measured),
            "drift_hours": drift,
            "agrees": abs(drift) < 0.01,
            "exceeds_half_hour": exceeds_half_hour,
            "exceeds_one_hour": exceeds_half_hour,
            "note": ("registered offset matches the broker's live clock"
                     if abs(drift) < 0.01 else
                     ("registered offset differs from the broker's live clock by >0.5h"
                      if exceeds_half_hour else
                      "registered offset differs from the broker's live clock; "
                      "the day boundary is offset by this much"))}


def verdict(symbol: Optional[str] = None, proposed_risk: float = 0.0,
            *, observe: bool = False,
            state_ref: Optional[CanonicalState] = None) -> Dict[str, Any]:
    """Evaluate the connected account against its policy.

    `observe` folds the reading into the durable baseline (advancing the
    low-water marks). The polling path observes; the governor does not, because a
    governor veto must not be able to move the reference points the next veto is
    measured against.
    """
    from challenge.service import challenge_service as svc

    account_id = connected_account_id(state_ref)
    policy = live_policy(state_ref)
    inputs = account_inputs(state_ref)
    if observe:
        svc.observe(account_id, equity=inputs["equity"],
                    balance=inputs["balance"], margin=inputs["margin"],
                    open_risk=inputs["open_risk"],
                    server_utc_offset_hours=server_utc_offset_hours(policy))
    result = svc.evaluate(
        account_id, policy,
        equity=inputs["equity"], balance=inputs["balance"],
        margin=inputs["margin"], open_risk=inputs["open_risk"],
        proposed_risk=float(proposed_risk or 0.0), symbol=symbol,
        server=getattr(getattr(state_ref, "account", None), "server", None)
        or None)
    result["managed"] = policy is not None
    result["program"] = configured_program()
    return result


def safe_room_usd(result: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Cash the account may still put at risk, after the §34.9 safety buffer.

    None when the figure is not known. Sizing treats None as "no cap from here"
    because a refusal has already been raised by then; it must not invent a
    number, and it must not treat unknown as zero either, since zero would be a
    claim about the account that nobody has evidence for.
    """
    report = (result or {}).get("headroom") or {}
    # `headroom_report` nests its figures under "dimensions"; reading them off the
    # report root finds nothing, rooms stays empty, and the cap silently
    # returns None. That is the failure mode this whole function exists to
    # prevent -- §34.9's "final size must remain within the strictest applicable
    # constraint" quietly not applying, with the trade looking correctly sized.
    dimensions = report.get("dimensions") or {}
    rooms: List[float] = []
    for dimension in ("daily_loss", "max_drawdown"):
        head = dimensions.get(dimension) or {}
        if not head.get("is_known"):
            continue
        remaining = head.get("remaining")
        if remaining is None:
            continue
        rooms.append(max(0.0, float(remaining) - float(head.get("buffer") or 0.0)))
    return min(rooms) if rooms else None
