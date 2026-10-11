"""Account ↔ strategy bindings: the seam between the Research and Account planes.

The research lab (`research/strategy_lab`) produces strategies, and it owns them.
No trading account owns a strategy, and no account may modify one: a strategy that
belongs to an account is a fork waiting to happen, because "which version is live
on A1" would then have as many answers as there are accounts.

What an account *may* have is a **binding** — a permission plus a risk context:

    research lab                accounts plane
    ────────────                ─────────────
    registry.json               accounts
      strategy_id                 account_id
      variant_hash   ──bind──►    status
      stage                       governance_state
                                 risk_override_json
                                 allowed_sessions_json

Two rules make this safe, and both are enforced here rather than documented and
hoped for.

**A binding may only name what the registry already cleared.** `bind()` verifies
the strategy exists and, when a stage is required, that it is at or above the
floor. A row naming a variant the research plane has never heard of is the exact
failure this prevents: it reads later as "already approved" to anything that only
asks whether a binding exists.

**A binding never authorises a trade.** There is no `grants_trade_permission` here
and no method returning one. The Risk Governor remains the only authority that
decides whether an order may be placed, and it decides that fresh, against the
promotion stage, the challenge window and the account's policy. A cached boolean
would be a second answer to that question, and it would still read `True` after a
challenge expired — the precise P0 defect the fail-closed work removed.

So `eligible_strategies()` answers a deliberately narrow question: *which bindings
are recorded and in an enabled state?* It is a registry read, not a verdict, and
it says so in the name.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from persistence.repositories_trades import AccountStrategyBindingRepository


# Binding lifecycle. Separate from the strategy's promotion stage on purpose:
# `pending`/`enabled`/`disabled` describe the operator's permission for one
# account, while `PromotionStage` describes the strategy's evidence. They are
# different facts and collapsing them would mean a strategy could be promoted into
# a permission it never earned.
BINDING_PENDING = "pending"
BINDING_ENABLED = "enabled"
BINDING_DISABLED = "disabled"

BINDING_STATES = (BINDING_PENDING, BINDING_ENABLED, BINDING_DISABLED)

# States in which a binding is considered at all. `pending` is excluded on purpose:
# a binding nobody approved is a request, and a registry that counted requests as
# permissions would answer "yes, this account may trade" from a form submission.
CONSIDERED_STATES = (BINDING_ENABLED,)

# The minimum promotion stage a strategy must have reached to be bindable at all.
# Below this the strategy has no validation report, so binding it would let an
# unvalidated idea reach an account's risk layer by way of a registry row.
BINDABLE_STAGES = ("validated", "paper", "production")


class StrategyBindingError(RuntimeError):
    """A binding was refused. The message says which rule refused it."""


def _registry_entries() -> List[Dict[str, Any]]:
    """The research plane's own entries, or `[]` when it cannot be read.

    An unreadable registry is `[]` and never a guess, matching
    `operations.live_engine.promotion_cleared_strategies()`. The difference is
    deliberate and matters: that function feeds an *arming* decision and being
    empty blocks Live, while this feeds a *binding* decision and being empty
    refuses the bind. Both fail closed; they just fail at different doors.
    """
    try:
        from research.strategy_lab.priors import registry_path_for
        import os

        path = registry_path_for()
        if not path or not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
        return [e for e in entries if isinstance(e, dict)] if isinstance(
            entries, list) else []
    except Exception:  # noqa: BLE001
        return []


def registry_variant(strategy_id: str) -> Optional[Dict[str, Any]]:
    """The research plane's record for one strategy id, or None."""
    sid = str(strategy_id or "").strip()
    if not sid:
        return None
    for entry in _registry_entries():
        if str(entry.get("strategy_id") or "").strip() == sid:
            return entry
    return None


class AccountStrategyBindings:
    """Domain vocabulary over `AccountStrategyBindingRepository`."""

    def __init__(self, repo: Optional[AccountStrategyBindingRepository] = None
                 ) -> None:
        self._repo = repo or AccountStrategyBindingRepository()

    # -- binding ----------------------------------------------------------

    def bind(self, *, account_id: str, strategy_id: str, variant_hash: str = "",
             status: str = BINDING_PENDING,
             risk_override_json: Optional[str] = None,
             allowed_sessions_json: Optional[str] = None,
             bound_by_user_id: Optional[str] = None,
             require_known_strategy: bool = True) -> Dict[str, Any]:
        """Record that an account may consider this strategy version.

        Refuses, rather than recording, when the research plane does not know the
        strategy or knows it only below `BINDABLE_STAGES`. A binding is a claim
        about governed work, and recording an unfounded one is how an unvalidated
        strategy acquires an account without ever passing a gate.

        `require_known_strategy=False` exists for the migration case only, where a
        binding must be recorded before the lab can see it. It is a refusal the
        caller has to ask for by name, not a default.
        """
        sid = str(strategy_id or "").strip()
        # Refuse the empty case first, and as a ValueError. Letting it fall
        # through to the registry lookup would report an empty id as "not in the
        # research registry" -- true, and useless, because it sends the caller
        # looking for a strategy that was never named.
        if not sid:
            raise ValueError("a binding needs the strategy it binds")
        if status not in BINDING_STATES:
            raise StrategyBindingError(
                f"unknown binding status {status!r}; expected one of "
                f"{BINDING_STATES}")

        if require_known_strategy:
            entry = registry_variant(sid)
            if entry is None:
                raise StrategyBindingError(
                    f"strategy {sid!r} is not in the research registry; a binding "
                    f"may only name a strategy the lab has produced")
            stage = str(entry.get("stage") or "").strip().lower()
            if stage not in BINDABLE_STAGES:
                raise StrategyBindingError(
                    f"strategy {sid!r} is at stage {stage or 'unknown'!r}; only "
                    f"{BINDABLE_STAGES} may be bound to an account")
            known = str(entry.get("variant_hash") or "").strip()
            if variant_hash:
                if known and known != str(variant_hash).strip():
                    raise StrategyBindingError(
                        f"variant mismatch for {sid!r}: registry says "
                        f"{known!r}, caller said {variant_hash!r}; binding the "
                        f"wrong variant is a silent strategy substitution")
            else:
                # The variant is a fact about the strategy, not about the caller.
                # Binding with no hash stores the registry's own, so the row is
                # always traceable back to the exact researched version.
                variant_hash = known

        return self._repo.bind(
            account_id=account_id, strategy_id=sid, variant_hash=variant_hash,
            status=status, risk_override_json=risk_override_json,
            allowed_sessions_json=allowed_sessions_json,
            bound_by_user_id=bound_by_user_id)

    def unbind(self, account_id: str, strategy_id: str,
               variant_hash: str = "") -> bool:
        return self._repo.unbind(account_id, strategy_id,
                                 self._variant_or_current(
                                     account_id, strategy_id, variant_hash))

    def set_status(self, account_id: str, strategy_id: str, status: str, *,
                   governance_state: str = "",
                   variant_hash: str = "") -> bool:
        if status not in BINDING_STATES:
            raise StrategyBindingError(
                f"unknown binding status {status!r}; expected one of "
                f"{BINDING_STATES}")
        return self._repo.set_status(
            account_id, strategy_id, status,
            governance_state=governance_state,
            variant_hash=self._variant_or_current(
                account_id, strategy_id, variant_hash))

    def _variant_or_current(self, account_id: str, strategy_id: str,
                            variant_hash: str) -> str:
        """Resolve the row the operator means.

        The repo keys a row by (account, strategy, variant). `get()` already
        reads "this strategy" as the most recently bound variant when no digest
        is named; `set_status` and `unbind` must mean the same row, or an
        operator who binds with `v3` and later disables "it" would be told their
        write matched nothing. An absent row has nothing to resolve to, so the
        empty digest passes through and the repo's no-match `False` stays honest.
        """
        if str(variant_hash or "").strip():
            return str(variant_hash).strip()
        row = self.get(account_id, strategy_id)
        return str(row.get("variant_hash") or "") if row else str(variant_hash)

    # -- lookup -----------------------------------------------------------

    def get(self, account_id: str, strategy_id: str,
            variant_hash: str = "") -> Optional[Dict[str, Any]]:
        """The binding for a strategy, or None.

        With `variant_hash` it is exact. Without it, the most recently bound
        variant is returned: `bind()` keys a variant, but an operator asking "is
        this strategy bound?" means the strategy, not one digest of it, and making
        them recall the hash would turn a lookup into a pop-quiz on the registry.
        """
        account_id = str(account_id or "").strip()
        strategy_id = str(strategy_id or "").strip()
        if not account_id or not strategy_id:
            return None
        if str(variant_hash or "").strip():
            return self._repo.get(account_id, strategy_id, variant_hash)
        rows = self._repo.list_for_account(account_id)
        matches = [r for r in rows if str(r.get("strategy_id") or "") == strategy_id]
        if not matches:
            return None
        matches.sort(key=lambda r: float(r.get("bound_at") or 0.0), reverse=True)
        return matches[0]

    def for_account(self, account_id: str, *, status: str = ""
                    ) -> List[Dict[str, Any]]:
        return self._repo.list_for_account(account_id, status=status)

    def for_strategy(self, strategy_id: str) -> List[Dict[str, Any]]:
        """Every account this strategy version is bound to.

        The Research Plane asks this when it asks "where does this strategy
        actually run?". One strategy on many accounts is the expected case.
        """
        return self._repo.list_for_strategy(strategy_id)

    def eligible_strategies(self, account_id: str) -> List[str]:
        """Strategy ids this account has an *enabled* binding for.

        Named "eligible", not "cleared" or "allowed", because that is all it is: a
        registry read. It does not know the promotion stage, the challenge window,
        the connection or the risk state, and it must never be read as the
        Risk Governor's verdict. `promotion_cleared_strategies()` is that verdict's
        input; a caller wanting a tradeable set needs both.
        """
        return sorted({
            str(b.get("strategy_id") or "")
            for b in self._repo.list_for_account(
                account_id, status=BINDING_ENABLED)
            if str(b.get("strategy_id") or "")
        })

    # -- reporting --------------------------------------------------------

    @staticmethod
    def summary(account_id: str,
                repo: Optional[AccountStrategyBindingRepository] = None
                ) -> Dict[str, Any]:
        """Bindings plus the research stage each names, for a status endpoint.

        The stage is read live from the registry rather than cached on the row, so
        a quarantine landed through governance shows up here without a backfill.
        """
        repo = repo or AccountStrategyBindingRepository()
        rows = repo.list_for_account(account_id)
        enriched = []
        for row in rows:
            entry = registry_variant(str(row.get("strategy_id") or ""))
            enriched.append({
                **row,
                "registry_stage": (str(entry.get("stage") or "").strip().lower()
                                   if entry else None),
                "in_registry": entry is not None,
            })
        by_state: Dict[str, int] = {}
        for row in enriched:
            key = str(row.get("status") or "unknown")
            by_state[key] = by_state.get(key, 0) + 1
        return {
            "account_id": str(account_id or ""),
            "count": len(enriched),
            "by_status": by_state,
            "bindings": enriched,
            "is_authorisation": False,
            "authoritative_body": "risk/governor.py",
        }
