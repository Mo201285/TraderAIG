"""Which tournament program governs an account, and why.

The failure these guard is not "wrong number" but "wrong program": a monthly
account judged by a 24-hour tournament's terms, or a $10,000 balance measured
against a $100,000 drawdown. Both produce confident, wrong, load-bearing numbers,
which is the whole class this codebase treats as worse than refusing.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,  # noqa: E402
                              Restriction, RuleValue)
from challenge.programs import (catalog, find_binding, programs_in_force,  # noqa: E402
                                resolve_program)
from challenge.registry import PolicyRegistry  # noqa: E402

SRC = "For Traders tournament rules, Oct 2026"
SERVER = "FTTrading-Server"


def _policy(program, *, version="v1", size=100_000.0, frm=None, until=None,
            server=SERVER, provider="For Traders", symbols=("EURUSD",)):
    return ChallengePolicy(
        provider=provider, program=program, account_size=size,
        policy_version=version, server=server,
        effective_from=frm, effective_until=until,
        profit_target=RuleValue.known(0.10, source=SRC),
        daily_loss_limit=RuleValue.known(0.10, source=SRC),
        max_drawdown=RuleValue.known(0.10, source=SRC),
        minimum_trading_days=RuleValue.not_applicable(source=SRC,
                                                      note="24-hour tournament"),
        max_leverage=RuleValue.known(500, source=SRC),
        drawdown_type=DrawdownType.TRAILING,
        instruments=InstrumentPolicy(allowed_symbols=list(symbols),
                                     default=Restriction.DENIED, source=SRC),
        overnight=Restriction.ALLOWED, weekend=Restriction.ALLOWED,
        server_utc_offset_hours=1.0)


def _registry(*policies):
    reg = PolicyRegistry()
    for p in policies:
        reg.register(p)
    return reg


def test_a_registered_program_is_offered_by_its_provider():
    """The catalogue answers a question nothing in the system could before."""
    reg = _registry(_policy("wednesday-clash", size=10_000.0),
                    _policy("weekend-crypto-clash", symbols=("BTCUSD",)))
    names = [e["program"] for e in catalog(reg, "For Traders")]
    assert names == ["wednesday-clash", "weekend-crypto-clash"]
    assert catalog(reg, "Some Other Broker") == []


def test_a_bound_account_takes_its_program_over_everything_else():
    """A recorded, sourced claim outranks the open window and the default.

    Both tournaments are open at `on`, so the window step alone would resolve to
    whichever is alphabetically first. The binding is what makes the answer the
    operator's instead.
    """
    reg = _registry(_policy("wednesday-clash", frm="2026-10-01T00:00:00",
                            until="2026-10-31T00:00:00"),
                    _policy("weekend-crypto-clash", frm="2026-10-01T00:00:00",
                            until="2026-10-31T00:00:00"))
    bindings = [{"account_login": "5150", "server": SERVER,
                 "provider": "For Traders", "program": "weekend-crypto-clash",
                 "source": "signup confirmation 2026-10-01"}]
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        bindings=bindings, default="wednesday-clash",
                        on="2026-10-09T15:30:00")
    assert d.program == "weekend-crypto-clash"
    assert d.reason == "binding"
    assert d.source == "signup confirmation 2026-10-01"


def test_a_binding_naming_an_unregistered_program_says_so():
    """Silently falling through would apply terms nobody chose."""
    reg = _registry(_policy("wednesday-clash"))
    bindings = [{"account_login": "5150", "server": SERVER,
                 "provider": "For Traders", "program": "never-registered",
                 "source": "an operator typo"}]
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        bindings=bindings)
    assert d.program == "never-registered"
    assert d.reason == "binding_without_policy"
    assert "no policy" in d.detail


def test_a_binding_without_a_program_is_not_a_program():
    reg = _registry(_policy("wednesday-clash"))
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        bindings=[{"account_login": "5150", "server": SERVER,
                                   "provider": "For Traders", "program": "  "}])
    assert d.program is None
    assert d.reason == "binding_without_program"


def test_one_open_window_identifies_the_program():
    """The window is real evidence: a tournament in progress has live accounts."""
    reg = _registry(_policy("wednesday-clash", frm="2026-10-07T13:00:00",
                            until="2026-10-08T13:00:00"))
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        on="2026-10-07T13:30:00")
    assert d.program == "wednesday-clash"
    assert d.reason == "window"


def test_two_open_windows_refuse_rather_than_pick():
    """Overlapping tournaments on one server are indistinguishable without a binding.

    This is the case that makes the whole module necessary: choosing one of two
    live programs would apply one tournament's terms to another tournament's
    balance, and nothing downstream would ever notice.
    """
    reg = _registry(_policy("wednesday-clash", frm="2026-10-07T13:00:00",
                            until="2026-10-20T00:00:00"),
                    _policy("weekend-crypto-clash", frm="2026-10-07T13:00:00",
                            until="2026-10-20T00:00:00"))
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        on="2026-10-09T15:30:00")
    assert d.program is None
    assert d.reason == "ambiguous"
    assert d.candidates == ["wednesday-clash", "weekend-crypto-clash"]
    assert "cannot be told apart" in d.detail


def test_a_closed_window_is_not_an_open_one():
    """`effective_until` is the tournament's end, and it must bind."""
    reg = _registry(_policy("wednesday-clash", frm="2026-10-07T13:00:00",
                            until="2026-10-08T13:00:00"))
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        default="", on="2026-10-08T13:00:01")
    assert d.program is None
    assert d.reason == "unresolved"


def test_the_deployment_default_is_the_last_resort_not_the_first():
    """It answers for an account with nothing else, and only that.

    The policy here is scoped to another server, so no window is open on this one
    and the default is what remains. When a program IS in force the window step
    wins instead -- which is the ordering this test's neighbour checks.
    """
    reg = _registry(_policy("wednesday-clash", server="OtherBroker-Server"))
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        default="wednesday-clash")
    assert d.program == "wednesday-clash"
    assert d.reason == "default_without_policy"

    bound = _registry(_policy("wednesday-clash"))
    d2 = resolve_program(bound, "For Traders", login="5150", server=SERVER,
                         default="wednesday-clash")
    assert d2.program == "wednesday-clash"
    assert d2.reason == "window", "an open program must beat the default"


def test_an_unbound_account_with_no_default_is_unresolved():
    """Silence about an account's terms resolves restrictively."""
    reg = _registry(_policy("wednesday-clash", frm="2026-10-07T13:00:00"))
    d = resolve_program(reg, "For Traders", login="5150", server="Other-Server",
                        default="")
    assert d.program is None
    assert d.reason == "unresolved"
    assert not d.resolved


def test_another_servers_tournament_is_never_offered():
    """A tournament written from one broker's document decides nothing on another."""
    reg = _registry(_policy("wednesday-clash", server="OtherBroker-Server"))
    assert programs_in_force(reg, "For Traders", SERVER) == []
    d = resolve_program(reg, "For Traders", login="5150", server=SERVER,
                        default="", on="2026-10-07T13:30:00")
    assert d.program is None


def test_an_exact_binding_beats_a_broker_neutral_one():
    neutral = [{"account_login": "5150", "server": "",
                "provider": "For Traders", "program": "monthly",
                "source": "the signup page, which names no server"}]
    exact = dict(neutral[0], server=SERVER, program="wednesday-clash")
    assert find_binding([neutral[0], exact], "5150", SERVER)["program"] == \
        "wednesday-clash"
    assert find_binding([neutral[0]], "5150", SERVER)["program"] == "monthly"
    assert find_binding([], "5150", SERVER) is None
    assert find_binding(neutral, "", SERVER) is None


@pytest.mark.parametrize("login", [None, "", 0])
def test_an_account_with_no_login_cannot_be_bound_by_accident(login):
    """A zero/absent login is how an unconnected state looks; it must not match."""
    rows = [{"account_login": "5150", "server": SERVER, "program": "monthly"}]
    assert find_binding(rows, login, SERVER) is None
