"""Wiring the challenge layer to the account facts the rest of the system already has.

34.11 requires challenge accounts to use the same engine, risk and execution
architecture as live accounts, so this module opens nothing, places nothing, and
owns no account state. It reads the canonical state that the MT5 sync loop is
already maintaining and answers the policy questions over it.

**The restart hazard, stated up front because it is the sharpest edge here.**
The numbers that decide a static-drawdown account -- its opening equity and its
all-time low -- are a *history*, and a history held in memory does not survive
the watchdog restart that this 24/7 host performs routinely. An account that
breached 4% and recovered would come back after a restart with no memory of the
breach, be scored at zero used drawdown, and be handed ALLOW. That is precisely
the failure this layer exists to prevent, arriving through the memory subsystem.

So a baseline is required before any account may be graded. Until the service
has both an opening equity and an observed low, the account reads ONBOARDING
and the permission is not ALLOW. It fails toward refusing rather than toward
trading, which is the only safe direction for a control whose whole purpose is
to notice a breach that has already happened. `ChallengeService.baseline_status`
reports the gap so it is visible rather than inferred.

**Both halves of that history are now durable, and the day boundary is the one
that is easy to miss.** The opening equity and the all-time low are written to
`challenge_baselines`, so a restart no longer returns a breached-and-recovered
account to full allowance. `day_epoch` is stored with them because a restart at
14:00 would otherwise treat 14:00 as the start of the trading day and hand the
account a fresh daily-loss allowance every single afternoon -- the daily limit
would be reset by a watchdog, which is the same class of bug as resetting it at
midnight. Account *state* is durable for the same reason in reverse: an account
whose last event was a halt must not come back as a clean ONBOARDING, because
the terminal states exist precisely so a failed account does not get to retry.

Persistence never promotes a fact. An `observed` row loads back as observed and
an `asserted` one as asserted -- a disk write cannot turn a guess into a
declaration, and a load path that upgraded origin would be laundering a guess
through storage. A store that cannot be reached is treated as empty, because the
alternative is raising out of the observation path and turning a storage problem
into an outage on the one host that must not go down; the cost of that choice is
that a missed write downgrades an account to untrusted, which is the direction
that costs an operator a re-declaration rather than an account its limits.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .headroom import AccountSnapshot, Permission, headroom_report, permission_for
from .policy import ChallengePolicy
from .registry import PolicyRegistry, registry as default_registry
from .state_machine import ChallengeState, ChallengeStateMachine, TransitionRefused

log = logging.getLogger(__name__)


class _DefaultStore:
    """Sentinel type: "you did not pass a store, so go and find the real one".

    A distinct object rather than a truthy flag, because `None` already has to
    mean "no store" for a caller that wants durability switched off.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<default durable store>"


_DEFAULT_STORE = _DefaultStore()

#: The account id used when no terminal is attached.
#:
#: A reading taken under this id is a measurement of the *absence* of an account,
#: not of an account. Row 735 already refused to grade a zero-equity reading --
#: "the disconnected account is the healthiest account on the platform" -- but
#: that guard lived in `has_baseline`, at the moment of grading. Persistence
#: moved the same reading somewhere new and unguarded: `observe` folded it in and
#: wrote a durable row for a non-account, `start_equity: 0.0`, which then came
#: back on the next boot as a restore failure. Fail-closed at grading time is
#: not fail-closed at write time, and a store that remembers the absence of an
#: account is a store that will one day remember it as a real one.
UNCONNECTED_ACCOUNT_ID = "unconnected"


def _load_store() -> Optional[Any]:
    """The durable store, or None when this deployment has none.

    Imported lazily and defensively on purpose. `challenge` must be importable
    with no database at all -- the test suite constructs services with no store,
    and a hard import of `persistence` here would make the risk package depend
    on storage being configured before it can even be reasoned about.
    """
    try:
        from persistence.repositories import ChallengeRepository
    except Exception as exc:  # noqa: BLE001
        log.warning("challenge baselines will not be durable: %s", exc)
        return None
    try:
        return ChallengeRepository()
    except Exception as exc:  # noqa: BLE001
        log.warning("challenge store unavailable; baselines stay in memory: %s", exc)
        return None


class _Baseline:
    """The account facts a policy decision needs and cannot recompute.

    Held per account so two accounts never share a baseline, which is 34.13's
    independence requirement expressed as a data-structure property rather than
    as a convention someone has to remember.
    """

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.start_equity: Optional[float] = None
        self.equity_low: Optional[float] = None
        self.day_epoch: Optional[int] = None
        self.day_start_equity: Optional[float] = None
        self.day_low_equity: Optional[float] = None
        self.last_seen: Optional[float] = None
        self.trading_days: int = 0
        # Provenance of `start_equity`. "observed" means we inferred it from
        # whatever the account happened to be worth the first time this process
        # saw it, which is a guess wearing a number's clothes. "declared" means
        # an operator supplied the provider's opening balance. Nothing is
        # "derived" here: a baseline reconstructed as balance-minus-P&L looks
        # rigorous and is wrong whenever the account took a deposit, a credit
        # or a bonus, and on a competition account the first of those is common.
        self.origin: str = "none"
        self.source: Optional[str] = None
        self.seeded_at: Optional[float] = None
        # Set when this baseline came back from the store. Kept so `/status`
        # can say the history was restored rather than rebuilt, which is the
        # difference an operator needs when a low-water mark looks too high.
        self.restored: bool = False

    def as_record(self) -> Dict[str, Any]:
        """The durable form. One shape, used for both save and load."""
        return {"account_id": self.account_id,
                "start_equity": self.start_equity,
                "equity_low": self.equity_low,
                "day_start_equity": self.day_start_equity,
                "day_low_equity": self.day_low_equity,
                "day_epoch": self.day_epoch,
                "trading_days": self.trading_days,
                "origin": self.origin,
                "source": self.source,
                "seeded_at": self.seeded_at}

    def declare(self, start_equity: float, source: str, *,
                verified: bool = False) -> None:
        """Record an opening balance that came from the provider's terms.

        This is the only path that makes a baseline trustworthy, and it is a
        separate call from `observe` precisely so that "we started watching"
        can never be mistaken for "we know how this account began".

        `verified` distinguishes "the document was in hand" from "someone says
        so". Only the former produces a gradable baseline; see
        `declare_baseline` for why a source string alone cannot be that proof.
        """
        self.start_equity = float(start_equity)
        self.origin = "declared" if verified else "asserted"
        self.source = (source or "").strip() or None
        self.seeded_at = time.time()
        if self.equity_low is None:
            self.equity_low = self.start_equity

    def observe(self, equity: float, balance: float,
                margin: float = 0.0, open_risk: float = 0.0,
                day_epoch: Optional[int] = None) -> None:
        """Fold one reading in, rolling the day when the epoch changes.

        The day roll is what returns a floating account's room. Doing it here
        rather than in the calculator is deliberate: the calculator must be a
        pure function of its inputs, or "what is my headroom" becomes a
        question with side effects.
        """
        equity = float(equity or 0.0)
        today = int(day_epoch if day_epoch is not None else time.time() // 86400)
        if self.start_equity is None:
            # Deliberately recorded as `observed`, not `declared`. This is the
            # current balance of an account that may have been trading for
            # weeks; treating it as the opening balance makes every drawdown
            # read as zero at the exact moment the account is furthest from its
            # high-water mark. The number is kept -- it is a real reading and
            # discarding it would help nobody -- but it is marked untrusted, and
            # `is_gradeable` refuses to let it produce an ALLOW.
            self.start_equity = float(balance or equity)
            self.origin = "observed"
            self.equity_low = equity
        if self.day_epoch is None or today != self.day_epoch:
            self.day_epoch = today
            self.day_start_equity = equity
            self.day_low_equity = equity
            self.trading_days += 1
        if self.equity_low is None or equity < self.equity_low:
            self.equity_low = equity
        if self.day_low_equity is None or equity < self.day_low_equity:
            self.day_low_equity = equity
        self.last_seen = time.time()
        self._margin = margin
        self._open_risk = open_risk

    def as_snapshot(self, equity: float, balance: float,
                    margin: float = 0.0, open_risk: float = 0.0) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            balance=float(balance or 0.0),
            equity=float(equity or 0.0),
            margin=float(margin or 0.0),
            open_risk=float(open_risk or 0.0),
            day_start_equity=self.day_start_equity,
            day_low_equity=self.day_low_equity,
            start_equity=self.start_equity,
            equity_low=self.equity_low,
            trading_days=self.trading_days,
        )

    @property
    def has_baseline(self) -> bool:
        """Whether we have an opening balance at all.

        Requires a *positive* opening equity, not merely a recorded one. A
        terminal that is attached but reporting nothing gives a reading of
        equity=0, balance=0, and a baseline built from that would score every
        limit as fully available -- a disconnected account would look like the
        healthiest account on the platform. Refusing to grade a zero baseline
        is the only safe reading of "we have not actually seen this account".
        """
        return bool(self.start_equity) and self.equity_low is not None

    @property
    def is_gradeable(self) -> bool:
        """Whether this baseline may produce an ALLOW.

        `has_baseline` is not enough, and the distinction is the whole point.
        An observed baseline answers "what is the account worth", which is not
        the question a drawdown limit asks -- that question is "what was the
        account worth when the challenge started", and the first observation
        cannot know it. Grading from an inferred opening balance makes a losing
        account look untouched, so an untrusted baseline is reported honestly
        and refused as a basis for permission.
        """
        return self.has_baseline and self.origin == "declared"

def _baseline_reason(baseline: "_Baseline") -> Optional[str]:
    """Why this baseline may not be graded, or None if it may.

    Two distinct refusals, and the wording keeps them apart on purpose. "Not
    enough data" is a temporary condition that watching fixes. "Inferred" is not
    temporary at all -- no amount of further watching will ever recover the
    opening balance of an account we joined late -- and telling an operator the
    first thing when the second is true would have them wait for a number that
    is never going to arrive.
    """
    if not baseline.has_baseline:
        return "baseline incomplete; refusing to grade the account"
    if baseline.origin == "asserted":
        return ("opening balance was asserted without the document in hand "
                "(`verified=false`), so the figure is someone's word rather than "
                "the provider's; the account is not graded until the terms are "
                "read and the declaration is re-entered as verified")
    if not baseline.is_gradeable:
        return ("opening equity was inferred from the first reading, not declared "
                "from the provider's terms; drawdown measured from it would "
                "understate the loss, so the account is not graded")
    return None


def _require_number(record: Dict[str, Any], field: str, account_id: str) -> Optional[float]:
    """Read a stored number, or refuse the row.

    `None` and "present but unreadable" are different states and must not both
    collapse to `None`. A field that was never written means "no observation",
    which is fine. A field that holds something that is not a number means the
    row is damaged, and quietly turning it into `None` erases the account's
    low-water mark -- so the one field the whole control measures from
    disappears and the account looks untouched. Rejecting the row instead costs
    a re-declaration, which is visible; accepting it costs a silent false
    "no breach recorded".
    """
    raw = record.get(field)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field}={raw!r} is not a number") from None
    # NaN compares false against everything, so a NaN low-water mark would pass
    # every minimum() downstream and silently win.
    if value != value:
        raise ValueError(f"{field} is NaN")
    return value


def _baseline_from_record(record: Dict[str, Any]) -> "_Baseline":
    """Rebuild a baseline from a stored row, or raise.

    Every failure here costs the account its baseline, which is the point: an
    unreadable history is not a licence to measure from a smaller one.
    """
    account_id = str(record.get("account_id") or "")
    if not account_id:
        raise ValueError("row has no account_id")

    start_equity = _require_number(record, "start_equity", account_id)
    if start_equity is not None and start_equity <= 0:
        # Row 735's zero-equity guard, restated for the read path: a
        # non-positive opening balance is not a baseline to measure drawdown
        # from, and loading it would grade against a division by nothing.
        raise ValueError(f"start_equity={start_equity} is not positive")

    baseline = _Baseline(account_id)
    baseline.start_equity = start_equity
    baseline.equity_low = _require_number(record, "equity_low", account_id)
    baseline.day_start_equity = _require_number(record, "day_start_equity",
                                                account_id)
    baseline.day_low_equity = _require_number(record, "day_low_equity",
                                              account_id)
    raw_days = record.get("trading_days")
    if raw_days is not None:
        try:
            baseline.trading_days = max(0, int(raw_days))
        except (TypeError, ValueError):
            raise ValueError(f"trading_days={raw_days!r} is not an integer") from None

    raw_epoch = record.get("day_epoch")
    if raw_epoch is not None:
        try:
            baseline.day_epoch = int(raw_epoch)
        except (TypeError, ValueError):
            raise ValueError(f"day_epoch={raw_epoch!r} is not an integer") from None

    baseline.origin = str(record.get("origin") or "observed")
    baseline.source = record.get("source")
    baseline.seeded_at = record.get("seeded_at")
    baseline.restored = True
    return baseline


class ChallengeService:
    """One account's challenge posture: its baseline, its policy, its state.

    Not a singleton here on purpose -- the module-level `challenge_service` is,
    but constructing one is cheap and takes an injected registry, so a test can
    give it an empty registry and never touch the process-wide one.
    """

    def __init__(self, registry: Optional[PolicyRegistry] = None, *,
                 store: Any = _DEFAULT_STORE,
                 restore: bool = True) -> None:
        self._registry = registry or default_registry
        self._baselines: Dict[str, _Baseline] = {}
        self._machines: Dict[str, ChallengeStateMachine] = {}
        self._lock = threading.RLock()
        # Three states, not two, and the distinction is load-bearing.
        #
        #   omitted  -> build the real durable store (production)
        #   None     -> no durability at all (a test that wants no database)
        #   object   -> use this store (a test's own file, or a broken fake)
        #
        # Collapsing "omitted" into "None" -- which is what a plain
        # `store: Optional[Any] = None` does -- makes those two requests
        # indistinguishable, so there is no way to ask for a service with no
        # store at all. The cost is not tidiness: a test that cannot isolate
        # itself writes its rows into the live database, and a test that cannot
        # turn durability off cannot check what the system does without it.
        if store is _DEFAULT_STORE:
            self._store = _load_store()
        else:
            self._store = store
        self._store_ok = self._store is not None
        self._restored: List[str] = []
        self._restore_failures: List[str] = []
        if restore and self._store is not None:
            self._restore_from_store()

    # -- durability -----------------------------------------------------

    def _restore_from_store(self) -> None:
        """Reload baselines and states so a restart forgets nothing.

        A row that cannot be turned back into a baseline is skipped and named in
        `_restore_failures` rather than loaded optimistically: half a baseline
        is exactly the object that produces confident wrong numbers, so a
        corrupt row must cost the account its baseline (untrusted, refusing)
        rather than give it a plausible one.
        """
        with self._lock:
            for record in self._safe(lambda s: s.load_baselines(), []):
                account_id = str(record.get("account_id") or "")
                if not account_id:
                    continue
                try:
                    baseline = _baseline_from_record(record)
                except (TypeError, ValueError) as exc:
                    self._restore_failures.append(f"{account_id}: {exc}")
                    continue
                self._baselines[account_id] = baseline
                self._restored.append(account_id)
            for record in self._safe(lambda s: s.load_states(), []):
                account_id = str(record.get("account_id") or "")
                state = str(record.get("state") or "")
                if not account_id or not state:
                    continue
                try:
                    machine = self.machine(account_id)
                    machine.restore(state)
                except (ValueError, TransitionRefused) as exc:
                    self._restore_failures.append(f"{account_id}: {exc}")

    def _safe(self, call, default):
        """Run a store call, degrading to `default` rather than raising.

        Losing a read costs a baseline and costs the account its permission;
        raising out of `observe` costs the API. On a 24/7 host the second is not
        a smaller problem, it is a different one.

        This also owns `_store_ok`, and it is the only thing that writes it.
        Setting the flag back to True at the call site looked harmless and was
        not: on a store where every write raised, the sequence was "flag False,
        then flag True", so `durability` reported `durable: true` precisely when
        the persistence was doing nothing. That is the same failure as row 734's
        revocation flag -- a health field that is true for the wrong reason --
        and the only safe arrangement is one writer that cannot be contradicted.
        """
        if self._store is None:
            return default
        try:
            result = call(self._store)
        except Exception as exc:  # noqa: BLE001
            self._store_ok = False
            log.warning("challenge store %s failed: %s",
                        getattr(call, "__name__", "call"), exc)
            return default
        self._store_ok = True
        return result

    def _persist_baseline(self, baseline: _Baseline) -> None:
        if self._store is None:
            return
        self._safe(lambda s: s.save_baseline(baseline.as_record()), None)

    def _persist_state(self, account_id: str, machine: Any) -> None:
        if self._store is None:
            return
        self._safe(lambda s: s.save_state(account_id, machine.state.value), None)

    @property
    def durability(self) -> Dict[str, Any]:
        """Whether the histories are actually durable in this process."""
        return {"durable": bool(self._store is not None) and self._store_ok,
                "store": type(self._store).__name__ if self._store else None,
                "restored": list(self._restored),
                "restore_failures": list(self._restore_failures)}

    # -- account wiring -------------------------------------------------

    def machine(self, account_id: str) -> ChallengeStateMachine:
        with self._lock:
            machine = self._machines.get(account_id)
            if machine is None:
                machine = ChallengeStateMachine(account_id)
                self._machines[account_id] = machine
            return machine

    def observe(self, account_id: str, *, equity: float, balance: float,
                margin: float = 0.0, open_risk: float = 0.0,
                day_epoch: Optional[int] = None) -> AccountSnapshot:
        """Record one reading of the real account and return the snapshot.

        `day_epoch` is injectable so a replay or a backfill can drive the day
        roll deliberately rather than waiting for UTC midnight -- the roll is
        what returns a floating account's room, and a control that can only be
        tested at midnight is a control nobody tests.
        """
        with self._lock:
            if account_id == UNCONNECTED_ACCOUNT_ID:
                # Refused at the write, not at the read. Everything downstream
                # already handles an account with no baseline correctly -- it
                # halts and reports every dimension unknown -- so the honest
                # result here is simply the unbased snapshot. What must not
                # happen is the row: a persisted `start_equity: 0.0` for a
                # string that is not an account is a fabricated baseline that
                # outlives the process that made it.
                return AccountSnapshot(account_id=account_id,
                                       balance=float(balance or 0.0),
                                       equity=float(equity or 0.0),
                                       margin=float(margin or 0.0),
                                       open_risk=float(open_risk or 0.0))
            baseline = self._baselines.get(account_id)
            if baseline is None:
                baseline = _Baseline(account_id)
                self._baselines[account_id] = baseline
            baseline.observe(equity, balance, margin, open_risk, day_epoch=day_epoch)
            self._persist_baseline(baseline)
            return baseline.as_snapshot(equity, balance, margin, open_risk)

    def snapshot(self, account_id: str, *, equity: float, balance: float,
                 margin: float = 0.0, open_risk: float = 0.0) -> AccountSnapshot:
        """Snapshot for the current reading, without folding it into the baseline.

        `observe` is the only method that may change the baseline, so reading
        the current position cannot quietly advance the reference points a
        decision is measured from. An account with no baseline does not get one
        created here: grading a never-observed account would make `has_baseline`
        report a state the account was never in, and would list the account as
        known when nothing about it is.
        """
        with self._lock:
            baseline = self._baselines.get(account_id)
            if baseline is None:
                return AccountSnapshot(account_id=account_id,
                                       balance=float(balance or 0.0),
                                       equity=float(equity or 0.0),
                                       margin=float(margin or 0.0),
                                       open_risk=float(open_risk or 0.0))
            return baseline.as_snapshot(equity, balance, margin, open_risk)

    def baseline_status(self, account_id: str) -> Dict[str, Any]:
        """Whether this account can be graded, and why not if it cannot."""
        with self._lock:
            baseline = self._baselines.get(account_id)
        if baseline is None:
            # Every key the populated branch returns is present here too, all
            # empty. The sparse version returned only `has_baseline` and
            # `reason`, which meant a caller indexing `status["equity_low"]`
            # raised KeyError -- and the account with no baseline is the
            # *default* state of every new account, so the crash landed on the
            # ordinary path rather than the damaged one. Same keys, same types,
            # nothing to infer at the call site.
            return {"account_id": account_id, "has_baseline": False,
                    "gradeable": False, "origin": "none", "source": None,
                    "restored": False, "start_equity": None, "equity_low": None,
"day_start_equity": None, "day_low_equity": None,
            "day_epoch": None,
            "trading_days": 0, "last_seen": None,
                    "reason": "no observation recorded yet; the opening equity "
                              "and low-water marks are unknown"}
        return {
            "account_id": account_id,
            "has_baseline": baseline.has_baseline,
            "gradeable": baseline.is_gradeable,
            "origin": baseline.origin,
            "source": baseline.source,
            "restored": baseline.restored,
            "start_equity": baseline.start_equity,
            "equity_low": baseline.equity_low,
            "day_start_equity": baseline.day_start_equity,
            "day_low_equity": baseline.day_low_equity,
            # Exposed because it is the field that decides whether today's low
            # belongs to today. Without it there is no way to tell, from the
            # outside, whether a restart will grant a fresh daily allowance.
            "day_epoch": baseline.day_epoch,
            "trading_days": baseline.trading_days,
            "last_seen": baseline.last_seen,
            "reason": _baseline_reason(baseline),
        }

    def declare_baseline(self, account_id: str, start_equity: float, *,
                         source: str,
                         verified: bool = False) -> Dict[str, Any]:
        """Seed an opening balance from the provider's terms.

        Separate from `observe` so the two can never be confused: watching an
        account is not the same as knowing how it began. A negative or zero
        opening balance is rejected outright rather than stored, because a
        baseline that cannot be true should not sit in the object waiting for
        someone to grade with it.

        `verified` is the honest answer to "did you read the document?". A
        source string is a promise, and a promise is checkable by nobody --
        which is exactly how a caller ends up writing
        "provider terms" against a number they guessed, because the field
        looked like it was doing work. So a declaration carries its own
        epistemic status: `verified` means the document was in hand when the
        number was entered, `asserted` means it is someone's word. An
        `asserted` baseline is deliberately **not** gradeable, so a guess
        cannot become a permission no matter how confidently it was typed.
        """
        if not (source or "").strip():
            raise ValueError("a declared baseline must name the source of the "
                             "opening balance")
        if account_id == UNCONNECTED_ACCOUNT_ID:
            # Same reason as `observe`: competition terms cannot be declared
            # for a string that stands in for the absence of an account. A
            # declaration is the one act here that makes an account gradable,
            # so it is the last place to accept a placeholder as an identity --
            # and it would be the durable one, outliving every restart.
            raise ValueError(f"{UNCONNECTED_ACCOUNT_ID!r} is not an account: "
                             f"declare a baseline for a broker login")
        amount = float(start_equity)
        if amount <= 0:
            raise ValueError(f"opening balance must be positive, got {start_equity!r}")
        with self._lock:
            baseline = self._baselines.get(account_id)
            if baseline is None:
                baseline = _Baseline(account_id)
                self._baselines[account_id] = baseline
            previous = {"origin": baseline.origin,
                        "start_equity": baseline.start_equity}
            baseline.declare(amount, source, verified=verified)
            self._persist_baseline(baseline)
        return {"account_id": account_id, "origin": baseline.origin,
                "start_equity": amount, "source": source.strip(),
                "gradeable": baseline.is_gradeable,
                "replaced": previous["start_equity"] if
                previous["origin"] != "declared" else None}

    def withdraw_baseline(self, account_id: str, *, reason: str) -> Dict[str, Any]:
        """Return an account to untrusted, keeping what watching has learned.

        A wrong declaration is worse than a missing one, and the only way to
        find out that a declared figure is wrong is to be able to take it back
        without killing the process. This drops the declared opening balance
        and lets the next observation rebuild the baseline as `observed` --
        the low-water marks survive, because they are measured facts, and it
        is the *origin* that is being withdrawn, not the account's history.
        """
        if not (reason or "").strip():
            raise ValueError("withdrawing a declared baseline requires a reason")
        with self._lock:
            baseline = self._baselines.get(account_id)
            if baseline is None:
                return {"account_id": account_id, "withdrawn": False,
                        "reason": "no baseline exists for this account"}
            was = {"origin": baseline.origin, "start_equity": baseline.start_equity}
            baseline.start_equity = None
            baseline.origin = "none"
            baseline.source = None
            baseline.seeded_at = None
            self._persist_baseline(baseline)
        return {"account_id": account_id, "withdrawn": True,
                "was_origin": was["origin"], "was_start_equity": was["start_equity"],
                "reason": reason.strip()}

    def forget(self, account_id: str) -> bool:
        with self._lock:
            had = self._baselines.pop(account_id, None) is not None
            self._machines.pop(account_id, None)
            return had

    # -- policy + decision ---------------------------------------------

    def policy_for(self, provider: str, program: str, *,
                   account_size: Optional[float] = None,
                   on: Optional[str] = None) -> Optional[ChallengePolicy]:
        return self._registry.resolve(provider, program, on=on,
                                      account_size=account_size)

    def evaluate(self, account_id: str, policy: Optional[ChallengePolicy], *,
                 equity: float, balance: float, margin: float = 0.0,
                 open_risk: float = 0.0, proposed_risk: float = 0.0,
                 symbol: Optional[str] = None, is_news_window: bool = False,
                 is_weekend: bool = False) -> Dict[str, Any]:
        """The 34.22 answer: state, headroom, permission -- and whether it counts.

        `counts` is the load-bearing field. It is False when the baseline is
        incomplete or the policy is unresolved, and the caller is expected to
        treat a permission of ALLOW as meaningless when it is False. That is
        what stops a restart from converting a breached account into an
        allowance.

        The baseline check is `gradeable`, not `has_baseline`. An inferred
        opening balance is a number we did not earn, and every dimension in the
        report is measured against it -- a 4% drawdown silently reads as 0% --
        so an untrusted baseline downgrades the decision to HALT rather than
        PROTECT. PROTECT would mean "you may trade, smaller", which is only
        defensible if the headroom figure it shrinks is true.
        """
        snapshot = self.snapshot(account_id, equity=equity, balance=balance,
                                 margin=margin, open_risk=open_risk)
        status = self.baseline_status(account_id)
        gradeable = bool(status.get("gradeable"))
        report = headroom_report(policy, snapshot, baseline_gradeable=gradeable)
        decision = permission_for(policy, snapshot, proposed_risk=proposed_risk,
                                  symbol=symbol, is_news_window=is_news_window,
                                  is_weekend=is_weekend)
        machine = self.machine(account_id)
        counts = gradeable and policy is not None
        reasons: List[str] = []
        if not gradeable:
            reasons.append(status.get("reason") or "baseline not trustworthy")
        if policy is None:
            reasons.append("no challenge policy resolves for this account")
        elif not policy.is_fully_specified:
            reasons.append("policy unverified: "
                           + ", ".join(policy.missing_rules()))
        if reasons and decision["permission"] == Permission.ALLOW.value:
            decision["permission"] = (Permission.HALT.value if not gradeable
                                      else Permission.PROTECT.value)
        if not gradeable:
            decision["checks"].append({
                "check": "baseline",
                "permission": Permission.HALT.value,
                "detail": status.get("reason") or "baseline not trustworthy",
            })
        return {
            "account_id": account_id,
            "snapshot": snapshot.as_dict(),
            "baseline": status,
            "headroom": report,
            "decision": decision,
            "state": machine.as_dict(),
            "counts": counts,
            "blocking_reasons": reasons,
        }

    def register_policy(self, policy: ChallengePolicy) -> Dict[str, Any]:
        """Register a policy version and report whether it is usable yet.

        The completeness report comes back on the registration call itself.
        Registering half a policy is a legitimate first step -- the operator
        will often know the drawdown rule before the rest -- but it has to be
        visibly incomplete at the moment it is registered rather than at the
        moment a trade is refused days later.
        """
        registered = self._registry.register(policy)
        return {
            "registered": True,
            "key": registered.key,
            "policy_version": registered.policy_version,
            "is_fully_specified": registered.is_fully_specified,
            "missing_rules": registered.missing_rules(),
            "effect": "usable for trading" if registered.is_fully_specified else
                      "registered but RESTRICTING: the account cannot be graded "
                      "until these rules are verified",
        }

    def transition(self, account_id: str, target: ChallengeState, *,
                   reason: str, actor: str = "system") -> Dict[str, Any]:
        machine = self.machine(account_id)
        try:
            record = machine.transition(target, reason=reason, actor=actor)
        except TransitionRefused as exc:
            return {"applied": False, "reason": exc.reason,
                    "state": machine.state.value}
        self._persist_state(account_id, machine)
        return {"applied": True, "transition": record.as_dict(),
                "state": machine.state.value}

    def recover(self, account_id: str, *, reason: str, authorized_by: str,
                conditions_met: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        machine = self.machine(account_id)
        try:
            record = machine.recover(reason=reason, authorized_by=authorized_by,
                                     conditions_met=conditions_met)
        except TransitionRefused as exc:
            return {"applied": False, "reason": exc.reason,
                    "state": machine.state.value}
        self._persist_state(account_id, machine)
        return {"applied": True, "transition": record.as_dict(),
                "state": machine.state.value}

    def accounts(self) -> List[str]:
        with self._lock:
            return sorted(self._baselines)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            durability = self.durability
            if not durability["durable"]:
                note = ("NOT durable — no store is bound in this process, so a "
                        "restart downgrades an account to untrusted and re-grants "
                        "a daily allowance")
            else:
                note = (f"durable in {durability['store']}; opening equity, "
                        f"low-water marks, day boundary and account state all "
                        f"survive a restart")
            return {
                "accounts": sorted(self._baselines),
                "registry": self._registry.as_dict(),
                "execution": "none — this layer reads account state and decides "
                             "permission; it never places or closes an order",
                "baseline_persistence": note,
                "durability": durability,
            }


#: Process-wide service, matching the repo's one-process-one-state convention.
challenge_service = ChallengeService()
