"""Live challenge-policy resolution: which terms govern the connected account.

This is the switch that decides whether the account is graded at all, and it had
no tests. The defect it existed for is a naming one, and a naming defect is
invisible to a suite that never exercises a real login's shape: MT5 reports
`broker` blank on a live account while `server` is populated, so reading the
firm from `broker` yields "" and the account reads as unmanaged -- identical, in
the output, to a deployment that has deliberately registered nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from challenge import live  # noqa: E402
from core.state import AccountState, CanonicalState  # noqa: E402


def _state(login="TEST-ACCT-LIVE", broker="", server="FTTrading-Server") -> CanonicalState:
    store = CanonicalState()
    store.account = AccountState(login=login, broker=broker, server=server,
                                 balance=100_000.0, equity=100_000.0)
    return store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROVIDER", raising=False)
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROGRAM", raising=False)


def test_a_configured_firm_is_used_even_though_mt5_reports_no_broker(monkeypatch):
    """The live account's own shape: `broker` empty, `server` populated.

    This is not a hypothetical -- it is what a real login looks like, and it is
    why the firm has to come from configuration and the server has to be passed
    separately.
    """
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "For Traders")
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROGRAM", "Tournaments")

    assert live.configured_provider(_state().account) == "For Traders"


def test_the_server_is_a_scope_and_never_a_provider(monkeypatch):
    """`FTTrading-Server` is which broker's document the terms were read from.

    Passing it as the provider would look up a firm by that name, find nothing,
    and report POLICY_UNKNOWN -- the same output as having no policy at all, so
    the mistake would be invisible in the one field that shows it.
    """
    monkeypatch.delenv("TRADERAIG_CHALLENGE_PROVIDER", raising=False)
    account = _state(broker="").account

    assert live.configured_provider(account) == ""
    assert account.server == "FTTrading-Server"


def test_a_reported_broker_is_still_honoured_when_no_firm_is_configured():
    """Some venues do fill `broker` in, and using it beats requiring env setup."""
    assert live.configured_provider(_state(broker="IC Markets").account) == "IC Markets"


def test_configuration_wins_over_a_reported_broker(monkeypatch):
    """An explicit firm beats whatever string the venue put in that field.

    `broker` is a display name on some venues and a company name on others, so a
    configured value that disagrees with it is the operator correcting a field
    the engine cannot interpret.
    """
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "For Traders")
    assert live.configured_provider(_state(broker="FTTrading").account) == "For Traders"


def test_no_provider_and_no_program_means_no_policy():
    """POLICY_UNKNOWN, not a guessed one.

    Both halves are required: a firm with no program, or a program with no firm,
    describes an account nobody has stated the terms of.
    """
    assert live.live_policy(_state()) is None

    import os
    os.environ["TRADERAIG_CHALLENGE_PROGRAM"] = "Tournaments"
    try:
        assert live.live_policy(_state()) is None
    finally:
        os.environ.pop("TRADERAIG_CHALLENGE_PROGRAM", None)


def test_the_server_is_passed_through_as_a_scope(monkeypatch):
    """The resolved call has to carry the server, or the scope is a no-op.

    Registering terms against one broker and resolving without the server filter
    would let them govern an account on another, which is the inheritance
    `matches_server` exists to refuse.
    """
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "For Traders")
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROGRAM", "Tournaments")
    seen = {}

    class _Service:
        def resolve_account_program(self, provider, *, login=None, server=None,
                                    on=None, default=None):
            from challenge.programs import ProgramDecision
            return ProgramDecision("Tournaments", "deployment_default",
                                   "test double", provider, server or "", "", [])

        def policy_for(self, provider, program, **kwargs):
            seen.update({"provider": provider, "program": program, **kwargs})
            return "policy"

    import challenge.service as service_module
    monkeypatch.setattr(service_module, "challenge_service", _Service())

    assert live.live_policy(_state()) == "policy"
    assert seen["provider"] == "For Traders"
    assert seen["server"] == "FTTrading-Server"


def test_a_blank_server_is_passed_as_absent_not_as_empty_string(monkeypatch):
    """An empty string is a value, and it is not a match.

    `resolve` filters on server scope; filtering for "" would match nothing and
    look like the same POLICY_UNKNOWN a missing policy gives. Passing None lets
    the registry's own "unscoped" path run instead.
    """
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "For Traders")
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROGRAM", "Tournaments")
    seen = {}

    class _Service:
        def resolve_account_program(self, provider, *, login=None, server=None,
                                    on=None, default=None):
            from challenge.programs import ProgramDecision
            return ProgramDecision("Tournaments", "deployment_default",
                                   "test double", provider, server or "", "", [])

        def policy_for(self, provider, program, **kwargs):
            seen.update(kwargs)
            return "policy"

    import challenge.service as service_module
    monkeypatch.setattr(service_module, "challenge_service", _Service())

    live.live_policy(_state(server=""))
    assert seen["server"] is None


def test_the_configured_providers_own_name_is_not_a_provider(monkeypatch):
    """`TRADERAIG_CHALLENGE_PROVIDER=TRADERAIG_CHALLENGE_PROVIDER` names no firm.

    The variable's own name came back as its value, so the lookup agreed with
    itself and the registry key read like a typo. It has to fall through to the
    account's own fields rather than be accepted as an identity.
    """
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "TRADERAIG_CHALLENGE_PROVIDER")

    assert live.configured_provider(_state()) == ""
    # A real firm in the same slot is still honoured.
    monkeypatch.setenv("TRADERAIG_CHALLENGE_PROVIDER", "For Traders")
    assert live.configured_provider(_state()) == "For Traders"


def test_a_failed_lookup_names_the_key_it_searched_beside_the_ones_it_has():
    """"No policy resolves" has to say WHICH no.

    An operator cannot tell a firm that was never configured from a firm that
    was configured under a name this deployment does not know, and those two
    need opposite fixes. So the diagnostic carries the searched key, every
    registered key, and the dimension that failed to match.
    """
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 Restriction)
    from challenge.registry import PolicyRegistry
    from challenge.service import ChallengeService

    registry = PolicyRegistry()
    registry.register(ChallengePolicy(
        provider="For Traders", program="Tournaments", account_size=100_000.0,
        policy_version="2026.09", server="FTTrading-Server",
        drawdown_type=DrawdownType.TRAILING,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED)))
    svc = ChallengeService(registry=registry)

    diag = svc.resolution_diagnostics("For Traders", "Classic",
                                      account_size=100_000.0,
                                      server="FTTrading-Server")
    assert diag["reason"] == "program_not_registered"
    assert "For Traders:Tournaments:2026.09" in diag["registered_keys"]
    assert "For Traders:Classic:FTTrading-Server" in diag["searched_key"]

    wrong_server = svc.resolution_diagnostics("For Traders", "Tournaments",
                                              server="OtherBroker-Server")
    assert wrong_server["reason"] == "server_mismatch"
    assert wrong_server["matched_keys"] == []

    other_firm = svc.resolution_diagnostics("Some Other Firm", "Tournaments")
    assert other_firm["reason"] == "provider_not_registered"


def test_the_status_route_explains_a_provider_mismatch_rather_than_saying_no(monkeypatch):
    """The reason has to reach the caller, not just the log.

    A generic "no challenge policy resolves for this account" is true of every
    possible cause, so it names no fix. This asserts the account is unmanaged
    AND that the reason string carries the searched key and the registered ones.
    """
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 Restriction)
    from challenge.registry import PolicyRegistry
    from challenge.service import ChallengeService

    registry = PolicyRegistry()
    registry.register(ChallengePolicy(
        provider="For Traders", program="Tournaments", account_size=100_000.0,
        policy_version="2026.09", server="FTTrading-Server",
        drawdown_type=DrawdownType.TRAILING,
        instruments=InstrumentPolicy(default=Restriction.ALLOWED)))
    svc = ChallengeService(registry=registry)

    monkeypatch.setattr(live, "configured_provider", lambda *a, **k: "Some Other Firm")
    monkeypatch.setattr(live, "configured_program", lambda *a, **k: "Tournaments")
    monkeypatch.setattr("core.state.state", lambda *a, **k: _state(), raising=False)

    report = svc.evaluate("TEST-ACCT-NOPOLICY", None, equity=100_000.0, balance=100_000.0)
    reasons = " ".join(report.get("blocking_reasons", []))
    assert "no challenge policy resolves" in reasons
    assert "searched_key" in reasons
    assert "registered_keys" in reasons
    assert "provider_not_registered" in reasons
