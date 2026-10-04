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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from core.state import CanonicalState, state

log = get_logger("challenge.live")

#: Program-resolution reasons where an operator deliberately named the program.
#: A binding is a per-account claim carrying a required `source`; the deployment
#: default is configuration somebody wrote. Both outrank any inference.
_BINDING_REASONS = frozenset({"binding", "binding_without_policy"})
_DEFAULT_REASONS = frozenset({"deployment_default", "default_without_policy"})
_EXPLICIT_REASONS = _BINDING_REASONS | _DEFAULT_REASONS


@dataclass(frozen=True)
class TournamentStatus:
    """Whether a tournament governs this account, and whether it is open.

    Three questions that used to be collapsed into one boolean, and which have to
    stay apart:

    - `applies` -- is this a tournament account at all?
    - `policy is not None` -- are its terms known well enough to grade it?
    - `window_open` -- is the tournament itself currently running?

    Collapsing them is what made a tournament that had ended read as an ordinary
    account with no rules, which silently switched the daily-loss and book-risk
    caps OFF at the moment they were still the reason the account existed.
    """

    applies: bool
    policy: Optional[Any] = None
    program: str = ""
    reason: str = ""
    detail: str = ""
    window_open: bool = True
    clock_known: bool = True
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None

    @property
    def managed(self) -> bool:
        """True when terms are known, so the caps can actually run."""
        return self.applies and self.policy is not None

    @property
    def can_open_new_position(self) -> bool:
        """Whether a new entry is permitted right now.

        Three independent refusals, each for its own reason:
        a declared tournament with no registered terms (§34.6 restricts), a
        tournament whose window is shut, and a window whose broker clock was
        never registered so its state cannot be known.
        """
        if not self.applies:
            return True
        if self.policy is None:
            return False
        if not self.clock_known:
            return False
        return bool(self.window_open)

    def refusal_reason(self) -> Optional[str]:
        """The machine-readable block, or None when entries are permitted."""
        if self.can_open_new_position:
            return None
        if self.policy is None:
            return "policy_unknown"
        if not self.clock_known:
            return "window_clock_unknown"
        return "tournament_window_closed"

    def as_dict(self) -> Dict[str, Any]:
        return {"applies": self.applies, "managed": self.managed,
                "program": self.program, "reason": self.reason,
                "detail": self.detail, "window_open": self.window_open,
                "clock_known": self.clock_known, "opens_at": self.opens_at,
                "closes_at": self.closes_at,
                "can_open_new_position": self.can_open_new_position,
                "refusal_reason": self.refusal_reason()}


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


def tournament_status(state_ref: Optional[CanonicalState] = None) -> TournamentStatus:
    """Everything the decision path needs to know about this account's tournament.

    The one thing this module exists to get right: a program that was named on
    purpose keeps governing the account even when its window is shut. Enforcement
    does not expire because a schedule ran out -- what the schedule decides is
    whether a *new entry* is allowed, and that is answered separately.
    """
    account = _state(state_ref).account
    provider = configured_provider(account)
    server = str(getattr(account, "server", "") or "").strip() or None
    login = getattr(account, "login", None)
    if not provider:
        return TournamentStatus(
            applies=False, reason="no_provider",
            detail="no provider is configured for this account, so no tournament "
                   "terms govern it")

    try:
        from challenge.service import challenge_service as svc

        decision = svc.resolve_account_program(provider, login=login, server=server)
    except Exception:  # noqa: BLE001
        log.exception("challenge program resolution failed")
        # An exception while working out whether this account is a tournament
        # account is not evidence that it is not one. Refusing entries is the
        # only reading of "I could not find out" that keeps the money safe.
        return TournamentStatus(
            applies=True, reason="error",
            detail="program resolution raised, so whether a tournament governs "
                   "this account is unknown; entries are refused")

    if decision.reason not in _EXPLICIT_REASONS:
        # window / ambiguous / unresolved / binding_without_program: either the
        # window is open (and the registry already proved it), or nothing names
        # this account deliberately.
        try:
            from challenge.service import challenge_service as svc

            policy = (svc.policy_for(provider, decision.program, server=server)
                      if decision.resolved else None)
        except Exception:  # noqa: BLE001
            log.exception("challenge policy resolution failed")
            policy = None
        return TournamentStatus(
            applies=bool(decision.resolved and policy is not None),
            policy=policy, program=decision.program or "",
            reason=decision.reason, detail=decision.detail, window_open=True)

    # Deliberately named. Grade it against the terms it was entered under,
    # whatever the window says, and answer the window separately.
    try:
        from challenge.service import challenge_service as svc

        governing = svc.resolve_ex(provider, decision.program, server=server,
                                   ignore_window=True)
        window = svc.resolve_ex(provider, decision.program, server=server)
    except Exception:  # noqa: BLE001
        log.exception("challenge window resolution failed")
        return TournamentStatus(
            applies=True, program=decision.program, reason="error",
            detail="window resolution raised, so it is unknown whether this "
                   "tournament is open; entries are refused", clock_known=False,
            window_open=False)

    if governing.policy is None:
        # A binding with no registered terms is a tournament account nobody has
        # written the rules for, and §34.6 resolves that in the restrictive
        # direction: refuse the entry.
        #
        # The deployment default is NOT the same claim. It is a fallback string,
        # and a deployment that sets it while registering no policies at all is
        # not running tournaments -- it is running ordinary accounts with a stale
        # default lying around. Reading that as "every account here is an ungraded
        # tournament" would halt an entire demo/paper deployment over a value
        # nobody was claiming anything specific about.
        if decision.reason in _DEFAULT_REASONS:
            return TournamentStatus(
                applies=False, program=decision.program,
                reason="program_not_registered",
                detail="no policy is registered for %r, so this deployment has no "
                       "tournament terms to enforce and the account is treated as "
                       "unmanaged" % decision.program)
        return TournamentStatus(
            applies=True, policy=None, program=decision.program,
            reason="program_without_terms", detail=governing.detail,
            window_open=window.window_open, clock_known=window.clock_known,
            opens_at=window.opens_at, closes_at=window.closes_at)

    detail = governing.detail
    if window.reason == "clock_unknown":
        detail = window.detail
    elif not window.window_open:
        detail = ("%s; the tournament window is shut, so new entries are "
                  "refused while its terms keep being enforced" % window.detail)
    return TournamentStatus(
        applies=True, policy=governing.policy, program=decision.program,
        reason=decision.reason, detail=detail,
        window_open=window.window_open, clock_known=window.clock_known,
        opens_at=window.opens_at, closes_at=window.closes_at)


def live_policy(state_ref: Optional[CanonicalState] = None):
    """The registered terms for the connected account, or None.

    None means "no terms are known", which the callers must distinguish from
    "everything is fine". It is the correct state for a deployment that trades
    its own money and has never registered challenge terms.

    The program is decided PER ACCOUNT, not read from one deployment-wide
    variable. A provider runs a catalogue of programs -- monthly, weekly,
    weekend -- and each of them reaches the terminal as an ordinary login, so
    the program cannot be a property of the process. `configured_program()`
    survives as the last-resort default inside that resolution and nothing else;
    it is what an unbound account falls back to, never what a bound one is
    governed by.

    Terms come back for any deliberately named program even when its window is
    shut. See `tournament_status` for why that is the safe order of operations.
    """
    return tournament_status(state_ref).policy


def window_status(state_ref: Optional[CanonicalState] = None) -> Dict[str, Any]:
    """The tournament window's state, for the console and the API."""
    return tournament_status(state_ref).as_dict()


def trading_permission(state_ref: Optional[CanonicalState] = None) -> Dict[str, Any]:
    """Whether this account may open a new position right now, and why not."""
    return tournament_status(state_ref).as_dict()


def can_open_new_position(state_ref: Optional[CanonicalState] = None) -> bool:
    """The narrow question the execution gate asks before admitting an entry."""
    return tournament_status(state_ref).can_open_new_position


def live_program_decision(state_ref: Optional[CanonicalState] = None):
    """Why this account resolves to the program it does, for the console.

    A halted account needs the sentence, not just the verdict: "unresolved" and
    "wrong program" are the same silence from the outside and completely
    different problems for whoever has to fix it.
    """
    account = _state(state_ref).account
    provider = configured_provider(account)
    server = str(getattr(account, "server", "") or "").strip() or None
    login = getattr(account, "login", None)
    if not provider:
        from challenge.programs import ProgramDecision
        return ProgramDecision(None, "no_provider",
                               "no provider is configured for this account",
                               "", server or "", "", [])
    try:
        from challenge.service import challenge_service as svc
        return svc.resolve_account_program(provider, login=login, server=server)
    except Exception:  # noqa: BLE001
        log.exception("challenge program resolution failed")
        from challenge.programs import ProgramDecision
        return ProgramDecision(None, "error", "program resolution raised",
                               provider, server or "", "", [])


def is_managed(state_ref: Optional[CanonicalState] = None) -> bool:
    """True when terms are known well enough to actually grade this account.

    This is the switch that keeps §34.15 out of ordinary trading: an account with
    no registered terms is not a challenge account, and the gate does not pretend
    otherwise by guessing rules for it.

    Distinct from `tournament_status().applies`, which asks whether a tournament
    governs the account at all. An account that declares a program nobody has
    registered terms for is *governed* (and therefore refuses entries) without
    being *managed* (because there is nothing to grade it against).
    """
    return tournament_status(state_ref).managed


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

    status = tournament_status(state_ref)
    account_id = connected_account_id(state_ref)
    policy = status.policy
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
    result["managed"] = status.managed
    result["applies"] = status.applies
    result["program"] = status.program
    result.update(status.as_dict())
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
