"""S6 XTAIG Economy: research-credit rewards tied to the wallet ledger (row 781).

The economy loop's missing half. Two reward paths already exist:
``accounts/referral_rewards.py`` grants a free *product entitlement* for a
verified referral, and ``governance/payments.py`` owns the *wallet ledger* for
what a user paid. This module closes the loop the roadmap named for S6 -- "tie
validation rewards to the payments wallet ledger": a strategy whose validation
**passes** earns its owner research credits (XTAIG) that land in that same
ledger as an EARN. One ledger, one balance, no second wallet.

Invariants, hard-wired here rather than trusted to callers:

* **Reward only real validation.** The award is computed from the strategy's
  *stored* ``ValidationReport`` (never a caller-supplied one), and only when it
  passed: a failing validation earns nothing and a strategy with no report is
  refused, never guessed at.
* **Deterministic and bounded.** :class:`DefaultResearchCreditModel` produces a
  named-component amount in ``[MIN_CREDITS, MAX_CREDITS]`` from evidence that
  exists (a base pass bonus plus profit-factor, out-of-sample fold win-rate and
  Monte-Carlo survival). The same report always yields the same credits -- no
  randomness, no fabricated score.
* **Beneficiary is recorded, never invented.** The owner is the strategy's
  RMI-05 asset-metadata ``owner``; a strategy with no recorded owner credits
  nothing rather than paying a guess.
* **Idempotent.** The credit reference is a content fingerprint of
  ``(strategy_id, stage, report)``; awarding twice credits once.
* **Never a trade gate.** No ``grants_trade_permission`` anywhere on this
  surface; every payload carries ``is_authorisation: False`` /
  ``trade_authority: "risk/governor.py"`` (rows 741/742).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from governance.payments import payments_service

# The ledger ``source``/provider tag a research credit is recorded under, so an
# earn is distinguishable from a billing charge in the one wallet.
REWARD_SOURCE = "research_rewards"

# The credit envelope: a passing validation is always worth something, and no
# single validation can mint an unbounded balance.
MIN_CREDITS = 50.0
MAX_CREDITS = 5_000.0
BASE_CREDITS = 100.0
QUALITY_BONUS = 400.0

# How the quality bonus is split across the evidence that exists.
QUALITY_WEIGHTS = {
    "profit_factor": 0.4,
    "oos_wins": 0.3,
    "survival": 0.3,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {**payload, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


@dataclass
class CreditAward:
    """A computed research credit: the amount plus the named components behind it."""

    credits: float
    components: Dict[str, float] = field(default_factory=dict)
    basis: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"credits": round(self.credits, 4),
                "components": dict(self.components), "basis": self.basis}


class ResearchCreditModel:
    """The pluggable credit seam: score a stored validation report."""

    def award(self, report: Dict[str, Any]) -> Optional[CreditAward]:
        raise NotImplementedError


class DefaultResearchCreditModel(ResearchCreditModel):
    """Deterministic, evidence-only research credit in ``[MIN_CREDITS, MAX]``."""

    def award(self, report: Dict[str, Any]) -> Optional[CreditAward]:
        report = report or {}
        if not report.get("passed"):
            return None  # a failing validation earns nothing
        pf = max(0.0, float(report.get("profit_factor") or 0.0))
        pf_norm = _clamp01((pf - 1.0) / 3.0)  # 1.0 -> 0, 4.0+ -> 1
        folds = int(report.get("walkforward_folds") or 0)
        wins = int(report.get("walkforward_wins") or 0)
        oos = _clamp01(wins / folds) if folds else 0.0
        survival = _clamp01(float(report.get("monte_carlo_survival") or 0.0))
        components = {
            "base": round(BASE_CREDITS, 4),
            "profit_factor": round(
                QUALITY_WEIGHTS["profit_factor"] * QUALITY_BONUS * pf_norm, 4),
            "oos_wins": round(
                QUALITY_WEIGHTS["oos_wins"] * QUALITY_BONUS * oos, 4),
            "survival": round(
                QUALITY_WEIGHTS["survival"] * QUALITY_BONUS * survival, 4),
        }
        credits = max(MIN_CREDITS, min(MAX_CREDITS, sum(components.values())))
        return CreditAward(
            credits=credits, components=components,
            basis=("passing validation: base pass bonus + weighted "
                   "profit-factor / out-of-sample fold wins / Monte-Carlo "
                   "survival, bounded to [%g, %g]" % (MIN_CREDITS, MAX_CREDITS)))


def _fingerprint(strategy_id: str, stage: str, report: Dict[str, Any]) -> str:
    """Content hash of the evidence a credit is tied to (idempotency key)."""
    payload = json.dumps({
        "strategy_id": strategy_id,
        "stage": stage,
        "passed": report.get("passed"),
        "samples": report.get("samples"),
        "win_rate": report.get("win_rate"),
        "expected_value": report.get("expected_value"),
        "profit_factor": report.get("profit_factor"),
        "max_drawdown": report.get("max_drawdown"),
        "oos_ev": report.get("oos_ev"),
        "walkforward_wins": report.get("walkforward_wins"),
        "walkforward_folds": report.get("walkforward_folds"),
        "monte_carlo_survival": report.get("monte_carlo_survival"),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class ResearchRewardService:
    """Award the research credit a validated strategy earned, into one wallet."""

    def __init__(self, *, payments=None, asset_layer=None,
                 model: Optional[ResearchCreditModel] = None) -> None:
        self._payments = payments
        self._assets = asset_layer
        self._model = model or DefaultResearchCreditModel()

    def _payments_service(self):
        return self._payments if self._payments is not None else payments_service

    def award_for_validation(self, strategy_id: str, *,
                             asset_layer=None) -> Dict[str, Any]:
        """Credit the owner of a validated strategy; idempotent and honest.

        Every refusal is a definite answer with a machine-readable ``reason``
        (``unknown_strategy`` / ``no_validation_recorded`` /
        ``validation_did_not_pass`` / ``no_owner_recorded``) and never a
        fabricated credit. On success the payload reports the credits, the
        reference, the named components and the resulting wallet balance.
        """
        strategy_id = str(strategy_id or "").strip()
        layer = asset_layer if asset_layer is not None else self._assets
        if not strategy_id or layer is None:
            return _enrich({"granted": False, "strategy_id": strategy_id,
                            "reason": "unknown_strategy", "credits": 0.0,
                            "detail": "no strategy to reward"})
        asset = layer.asset(strategy_id)
        if asset is None:
            return _enrich({"granted": False, "strategy_id": strategy_id,
                            "reason": "unknown_strategy", "credits": 0.0,
                            "detail": "no such strategy is registered"})
        report = asset.validation
        if not report:
            return _enrich({"granted": False, "strategy_id": strategy_id,
                            "reason": "no_validation_recorded", "credits": 0.0,
                            "detail": "the strategy has no validation report "
                                      "to reward yet"})
        award = self._model.award(report)
        if award is None:
            return _enrich({"granted": False, "strategy_id": strategy_id,
                            "reason": "validation_did_not_pass", "credits": 0.0,
                            "detail": "a reward is earned only by a passing "
                                      "validation"})
        owner = str((asset.metadata or {}).get("owner") or "").strip()
        if not owner:
            return _enrich({"granted": False, "strategy_id": strategy_id,
                            "reason": "no_owner_recorded", "credits": 0.0,
                            "detail": "no owner is recorded on the strategy "
                                      "asset; nothing is credited to a guess"})
        stage = getattr(asset.stage, "value", None) or str(asset.stage or "")
        ref = _fingerprint(strategy_id, stage, report)
        result = self._payments_service().credit(
            owner, award.credits, source=REWARD_SOURCE, ref=ref,
            description=f"research reward for {strategy_id}",
            details={"strategy_id": strategy_id, "stage": stage,
                     "family": asset.family.value,
                     "asset": asset.asset})
        return _enrich({
            "granted": bool(result.get("credited")),
            "duplicate": bool(result.get("duplicate")),
            "strategy_id": strategy_id,
            "user_id": owner,
            "credits": float(result.get("amount_usd", award.credits)),
            "ref": ref,
            "stage": stage,
            "components": award.components,
            "basis": award.basis,
            "wallet_balance": result.get("wallet_balance", 0.0),
            "reason": "" if result.get("credited") else "already_credited",
            "detail": result.get("error", ""),
        })

    @staticmethod
    def policy() -> Dict[str, Any]:
        """The credit model's public envelope (read-only, for the UI)."""
        return {
            "source": REWARD_SOURCE,
            "min_credits": MIN_CREDITS,
            "max_credits": MAX_CREDITS,
            "base_credits": BASE_CREDITS,
            "quality_bonus": QUALITY_BONUS,
            "weights": dict(QUALITY_WEIGHTS),
            "bounded_by": "wallet ledger (governance/payments.py credit)",
            "rewarded_on": "passing validation only",
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


__all__ = [
    "BASE_CREDITS",
    "CreditAward",
    "DefaultResearchCreditModel",
    "MAX_CREDITS",
    "MIN_CREDITS",
    "QUALITY_BONUS",
    "QUALITY_WEIGHTS",
    "REWARD_SOURCE",
    "ResearchCreditModel",
    "ResearchRewardService",
]
