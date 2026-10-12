"""Launch-readiness gate: pure evidence checks on a settings object.

``operations.launch.assess`` takes the *live* configuration and reports, from
the real values, whether the hard preconditions for accepting live orders are
met. It never enables anything, so these tests only inspect the report the
gate produces for a given (fake) config.
"""

import json
from types import SimpleNamespace

from operations.launch import (
    ADVISORY,
    HARD,
    assess,
    cex_armed,
    mt5_armed,
    payments_armed,
)


def _mt5(terminal="C:/MT5/terminal64.exe", login=1000, server="MetaQuotes-Demo"):
    return SimpleNamespace(terminal_path=terminal, login=login, server=server)


def _cex(mode="paper", live_allowed=False, venue="binance",
         binance_key="", binance_secret="",
         okx_key="", okx_secret="", okx_passphrase="",
         bybit_key="", bybit_secret=""):
    return SimpleNamespace(
        mode=mode, live_allowed=live_allowed, venue=venue,
        binance_api_key=binance_key, binance_api_secret=binance_secret,
        okx_api_key=okx_key, okx_api_secret=okx_secret,
        okx_passphrase=okx_passphrase,
        bybit_api_key=bybit_key, bybit_api_secret=bybit_secret)


def _payments(mode="sandbox", live_allowed=False, provider="sandbox",
              stripe_secret="", pi_key=""):
    return SimpleNamespace(
        mode=mode, live_allowed=live_allowed, provider=provider,
        stripe_secret_key=stripe_secret, pi_api_key=pi_key)


def _settings(mt5=None, cex=None, payments=None):
    # default = everything off: no login, paper CEX, sandbox payments
    return SimpleNamespace(
        mt5=mt5 or _mt5(login=0), cex=cex or _cex(),
        payments=payments or _payments())


def _ids(report):
    return {c["id"] for c in report["checks"]}


def _ok(report, identifier):
    for c in report["checks"]:
        if c["id"] == identifier:
            return c["ok"]
    raise KeyError(identifier)


def test_default_all_off_refuses_to_be_ready():
    """Out of the box the gate must say NOT ready, naming the hard blockers."""
    report = assess(_settings(), enforcement=False)
    assert report["ready"] is False
    assert "auth_enforced" in report["blocking"]
    assert "live_rail_armed" in report["blocking"]
    assert "live_gates_consistent" not in report["blocking"]
    assert report["is_authorisation"] is False
    assert report["trade_authority"] == "risk/governor.py"


def test_enforcement_alone_is_not_enough():
    """Auth on with no live rail must still refuse."""
    report = assess(_settings(), enforcement=True)
    assert report["ready"] is False
    assert "live_rail_armed" in report["blocking"]
    assert "auth_enforced" not in report["blocking"]


def test_mt5_rail_with_enforcement_is_ready():
    report = assess(_settings(mt5=_mt5()), enforcement=True)
    assert report["ready"] is True
    assert report["blocking"] == []


def test_cex_live_with_keys_is_ready():
    cex = _cex(mode="live", live_allowed=True, binance_key="k", binance_secret="s")
    report = assess(_settings(cex=cex), enforcement=True)
    assert _ok(report, "live_rail_armed") is True
    assert _ok(report, "live_gates_consistent") is True
    assert report["ready"] is True


def test_cex_half_armed_gate_blocks():
    """live_allowed on with no keys is a misconfiguration, not a launch."""
    cex = _cex(mode="live", live_allowed=True)
    report = assess(_settings(cex=cex), enforcement=True)
    assert report["ready"] is False
    assert "live_rail_armed" in report["blocking"]
    assert "live_gates_consistent" in report["blocking"]
    assert _ok(report, "cex_ready") is False


def test_okx_requires_passphrase():
    partial = _cex(mode="live", live_allowed=True, venue="okx",
                   okx_key="k", okx_secret="s")
    assert _ok(assess(_settings(cex=partial), enforcement=True),
               "live_gates_consistent") is False
    complete = _cex(mode="live", live_allowed=True, venue="okx",
                    okx_key="k", okx_secret="s", okx_passphrase="p")
    assert _ok(assess(_settings(cex=complete), enforcement=True),
               "live_gates_consistent") is True


def test_payments_half_armed_gate_blocks():
    """A payments live gate on without its provider key is blocking too."""
    pay = _payments(mode="live", live_allowed=True, provider="stripe")
    report = assess(_settings(payments=pay), enforcement=True)
    assert report["ready"] is False
    assert "live_gates_consistent" in report["blocking"]


def test_payments_armed_is_consistent():
    pay = _payments(mode="live", live_allowed=True, provider="stripe",
                    stripe_secret="sk-live-x")
    report = assess(_settings(mt5=_mt5(), payments=pay), enforcement=True)
    assert _ok(report, "live_gates_consistent") is True
    assert _ok(report, "payments_ready") is True
    assert report["ready"] is True


def test_mt5_priority_helpers():
    assert mt5_armed(_mt5()) is True
    assert mt5_armed(_mt5(login=0)) is False
    assert mt5_armed(_mt5(terminal="")) is False
    assert cex_armed(_cex(mode="live", live_allowed=True,
                          binance_key="k", binance_secret="s")) is True
    assert cex_armed(_cex(mode="paper", live_allowed=True,
                          binance_key="k", binance_secret="s")) is False
    assert payments_armed(_payments(mode="live", live_allowed=True,
                                    provider="stripe",
                                    stripe_secret="sk-live-x")) is True
    assert payments_armed(_payments(provider="sandbox")) is False


def test_hard_and_advisory_severities_are_complete():
    report = assess(_settings(), enforcement=False)
    assert {c["severity"] for c in report["checks"]} <= {HARD, ADVISORY}
    blocking_ids = {c["id"] for c in report["checks"]
                    if c["severity"] == HARD and not c["ok"]}
    assert report["blocking"] == sorted(report["blocking"])
    assert set(report["blocking"]) == blocking_ids
    # the three hard preconditions are always present
    assert {"auth_enforced", "live_rail_armed", "live_gates_consistent"} <= \
        _ids(report)


def test_registered_accounts_reported_as_advisory():
    none_report = assess(_settings(), enforcement=False)
    assert "registered_accounts" not in _ids(none_report)
    zero_report = assess(_settings(), enforcement=False,
                         registered_accounts=0)
    assert _ok(zero_report, "registered_accounts") is False
    assert zero_report["ready"] is False  # still blocked by hard checks
    three_report = assess(_settings(mt5=_mt5()), enforcement=True,
                          registered_accounts=3)
    assert _ok(three_report, "registered_accounts") is True
    assert three_report["ready"] is True


def test_secrets_never_serialize_into_the_payload():
    """Presence is reported; the key values themselves must never leak."""
    cex = _cex(mode="live", live_allowed=True,
               binance_key="k-BINANCE-HUSH-99", binance_secret="s-BINANCE-HUSH-99")
    pay = _payments(mode="live", live_allowed=True, provider="stripe",
                    stripe_secret="sk-live-STRIPE-HUSH-99")
    report = assess(_settings(cex=cex, payments=pay), enforcement=True)
    dumped = json.dumps(report)
    assert "k-BINANCE-HUSH-99" not in dumped
    assert "s-BINANCE-HUSH-99" not in dumped
    assert "sk-live-STRIPE-HUSH-99" not in dumped
    assert report["ready"] is True
