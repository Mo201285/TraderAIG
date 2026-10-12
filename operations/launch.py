"""Launch readiness: the honest, evidence-only go-live gate (S12 capstone).

Answers one question -- *is this deployment safe to accept live orders right
now?* -- from the real configuration, never from a promise. It **never enables
anything**: every live gate stays a human decision, and the route refuses to say
``ready`` while a hard precondition is unmet.

Hard preconditions (all must hold or ``ready`` is False):

1. ``auth_enforced`` -- authentication must be enforced; otherwise any caller
   that reaches the port acts as the acting principal.
2. ``live_rail_armed`` -- at least one live venue rail is genuinely armed:
   MT5 (terminal path + login + server) **or** CEX (``live_allowed`` +
   ``mode=live`` + the configured venue's keys present).
3. ``live_gates_consistent`` -- no *half-armed* live gate: a ``*_LIVE_ALLOWED``
   flag enabled without its key/venue closed is a misconfiguration, not a
   launch.

Advisory signals (reported, never blocking): MT5 readiness, CEX readiness,
payments readiness, the number of registered accounts.

Secrets are never read into the payload: only their *presence* is reported, so
the surface cannot leak keys by construction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Every payload denies being a trade authority.
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

HARD = "hard"
ADVISORY = "advisory"


# -- per-rail readiness helpers -------------------------------------------


def _cex_venue_keys_ready(cfg) -> bool:
    """The configured CEX venue's live keys are present (presence only)."""
    venue = str(getattr(cfg, "venue", "") or "").strip()
    api_key = str(getattr(cfg, f"{venue}_api_key", "") or "").strip()
    api_secret = str(getattr(cfg, f"{venue}_api_secret", "") or "").strip()
    if venue == "okx":
        passphrase = str(getattr(cfg, "okx_passphrase", "") or "").strip()
        return bool(api_key and api_secret and passphrase)
    return bool(api_key and api_secret)


def _payment_provider_key_ready(cfg) -> bool:
    """The configured payment provider's live key is present (presence only)."""
    provider = str(getattr(cfg, "provider", "") or "").strip().lower()
    if provider == "sandbox":
        return True
    if provider == "stripe":
        return bool(str(getattr(cfg, "stripe_secret_key", "") or "").strip())
    if provider == "pi":
        return bool(str(getattr(cfg, "pi_api_key", "") or "").strip())
    return False


def mt5_armed(cfg) -> bool:
    """The MT5 rail is fully declared: terminal + login + server."""
    terminal = str(getattr(cfg, "terminal_path", "") or "").strip()
    login = int(getattr(cfg, "login", 0) or 0)
    server = str(getattr(cfg, "server", "") or "").strip()
    return bool(terminal and server and login > 0)


def cex_armed(cfg) -> bool:
    """The CEX rail is fully armed: live gate on, mode live, keys present."""
    return (bool(getattr(cfg, "live_allowed", False))
            and str(getattr(cfg, "mode", "") or "").strip() == "live"
            and _cex_venue_keys_ready(cfg))


def payments_armed(cfg) -> bool:
    """The payments rail is fully armed: live gate on, mode live, key present."""
    return (bool(getattr(cfg, "live_allowed", False))
            and str(getattr(cfg, "mode", "") or "").strip() == "live"
            and _payment_provider_key_ready(cfg))


# -- the gate --------------------------------------------------------------


def assess(settings, *, enforcement: bool,
           registered_accounts: Optional[int] = None) -> Dict[str, Any]:
    """Build the readiness report from the real configuration.

    ``settings`` is the live ``core.config.Settings``; ``enforcement`` is the
    real auth-enforcement state at call time; ``registered_accounts`` is a
    best-effort count (None means the registry could not be read, and the check
    is omitted rather than assumed).
    """
    checks: List[Dict[str, Any]] = []

    def add(identifier: str, label: str, ok: bool, severity: str,
            detail: str) -> None:
        checks.append({"id": identifier, "label": label, "ok": bool(ok),
                       "severity": severity, "detail": detail})

    add("auth_enforced", "Authentication enforced", enforcement, HARD,
        "TRADERAIG_AUTH is on" if enforcement else (
            "TRADERAIG_AUTH is off -- any caller that reaches the port acts "
            "as the acting principal"))

    mt5 = mt5_armed(settings.mt5)
    cex = cex_armed(settings.cex)
    if mt5:
        rail_detail = "MT5 rail armed (terminal + login + server)"
    elif cex:
        rail_detail = "CEX rail armed (live gate on, mode=live, keys present)"
    else:
        rail_detail = (
            "no live rail armed: MT5 needs terminal+login+server; CEX needs "
            "live_allowed + mode=live + the configured venue's keys present")
    add("live_rail_armed", "A live venue rail is armed", mt5 or cex, HARD,
        rail_detail)

    cex_consistent = (not settings.cex.live_allowed) or cex
    pay_key_ready = _payment_provider_key_ready(settings.payments)
    pay_consistent = ((not settings.payments.live_allowed)
                      or (settings.payments.mode == "live" and pay_key_ready))
    add("live_gates_consistent", "No half-armed live gate",
        cex_consistent and pay_consistent, HARD,
        "every *LIVE_ALLOWED flag is either off or fully closed"
        if (cex_consistent and pay_consistent) else (
            "a live gate is enabled without its key/venue closed: CEX "
            "live_allowed or payments live_allowed is on while the rail is "
            "not armed"))

    add("mt5_ready", "MT5 rail ready", mt5, ADVISORY,
        "terminal + login + server present" if mt5 else
        "not armed (terminal/login/server missing)")
    add("cex_ready", "CEX rail ready", cex, ADVISORY,
        "live_allowed + mode=live + venue keys present" if cex else
        "not armed (live gate off, or mode/keys unmet)")
    add("payments_ready", "Payments live ready",
        payments_armed(settings.payments), ADVISORY,
        "live_allowed + mode=live + provider key present"
        if payments_armed(settings.payments) else
        "locked to sandbox/stub (live gate off or key missing)")
    if registered_accounts is not None:
        add("registered_accounts", "Accounts registered",
            registered_accounts > 0, ADVISORY,
            f"{registered_accounts} account record(s) in the registry")

    blocking = [c["id"] for c in checks
                if c["severity"] == HARD and not c["ok"]]
    ready = not blocking
    return {
        "ready": ready,
        "blocking": blocking,
        "checks": checks,
        "note": (
            "a readiness gate reports measured preconditions; it never "
            "enables a live gate -- flipping live stays an operator decision"),
        "is_authorisation": IS_AUTHORISATION,
        "trade_authority": TRADE_AUTHORITY,
    }


__all__ = [
    "ADVISORY",
    "HARD",
    "IS_AUTHORISATION",
    "assess",
    "cex_armed",
    "mt5_armed",
    "payments_armed",
    "TRADE_AUTHORITY",
]
