"""Secrets Vault tests — ENGINEERING MAST 28.18 Security Boundary.

The vault encrypts at rest (Windows DPAPI via ctypes) and NEVER returns secret
values over the API: status/list expose only set-bools. Writes are decision
endpoints gated by API_ACCESS (institutional) once an identity exists;
bootstrap (no identity) passes so a fresh control plane can enroll keys.
These tests must reset the process-global identity singleton AND the vault
module singleton around themselves so sibling suites keep clean state.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

import core.secrets_vault as sv  # noqa: E402
import governance.identity as gov  # noqa: E402

from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def temp_vault(tmp_path):
    """Point the module vault singleton at an isolated temp store."""
    old = sv.vault
    sv.vault = sv.SecretsVault(data_dir=tmp_path / "secrets")
    yield sv.vault
    sv.vault = old


@pytest.fixture(autouse=True)
def _reset_identity():
    idents = gov.identity
    users = idents._users
    subs = idents._subscriptions
    audit = idents._audit
    idents._users = {}
    idents._subscriptions = {}
    idents._audit = []
    yield
    idents._users = users
    idents._subscriptions = subs
    idents._audit = audit


def _spawn(client, plan: str, activate: bool):
    resp = client.post("/users", json={
        "email": f"sec-{sys.hash_info.width}-{abs(hash(plan))}@x.co",
        "display_name": "sec-test",
        "plan": plan})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    if activate:
        r = client.post(f"/users/{user_id}/subscription/activate",
                        json={"plan": plan})
        assert r.status_code == 200
    return user_id


# -- vault unit behavior ---------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_vault_roundtrip_encrypted_at_rest(tmp_path):
    v = sv.SecretsVault(data_dir=tmp_path)
    assert v.is_persistable()
    v.set("cex.okx.demo_api_secret",
          "super-secret-value-4F95BFD26BC431F13B5B89881D57F4EC")
    assert v.read("cex.okx.demo_api_secret") == \
        "super-secret-value-4F95BFD26BC431F13B5B89881D57F4EC"
    assert v.exists("cex.okx.demo_api_secret")
    raw = v.path.read_text(encoding="utf-8")
    assert "super-secret-value" not in raw  # nothing plaintext on disk
    assert v.secrets_leak() is False


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_vault_resolve_prefers_stored_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CEX_OKX_DEMO_API_SECRET", "env-value")
    v = sv.SecretsVault(data_dir=tmp_path)
    assert v.resolve("cex.okx.demo_api_secret") == "env-value"
    v.set("cex.okx.demo_api_secret", "vault-value")
    assert v.resolve("cex.okx.demo_api_secret") == "vault-value"
    v.delete("cex.okx.demo_api_secret")
    assert v.resolve("cex.okx.demo_api_secret") == "env-value"


def test_vault_unknown_slot_rejected(tmp_path):
    v = sv.SecretsVault(data_dir=tmp_path)
    with pytest.raises(KeyError):
        v.set("no/such/slot", "x")


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_short_secret_is_encrypted_and_not_a_false_leak(tmp_path):
    """A two-character password must not be read as a plaintext leak.

    A naive `value in raw` substring check reports a leak for the short value
    purely because two characters turn up somewhere in the file. The vault is
    fully encrypted here, and the detector must say so -- a false alarm on a
    security boundary is its own defect (invigilation: three live MT5 passwords
    were flagged this way while every entry was DPAPI ciphertext).
    """
    v = sv.SecretsVault(data_dir=tmp_path)
    v.set("mt5.a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4.password", "12")
    assert v.read("mt5.a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4.password") == "12"
    # the cipher is a binary blob, never the plaintext as a JSON string
    assert v.secrets_leak() is False


def test_secrets_leak_detects_a_plaintext_field(tmp_path):
    """A value stored outside the cipher blob is a real leak and is reported.

    The detector cannot rely on a backend: this writes an entry whose value sits
    in a plain field, which is exactly what a plaintext fallback would produce.
    """
    import json as _json
    v = sv.SecretsVault(data_dir=tmp_path)
    v._entries["cex.okx.api_key"] = {"set_at": 0.0, "value": "PLAINTEXT-LEAK-AAAAAA"}
    v.data_dir.mkdir(parents=True, exist_ok=True)
    v.path.write_text(_json.dumps({"version": 1, "backend": "plain",
                                   "entries": v._entries}), encoding="utf-8")
    assert v.secrets_leak() is True


# -- per-account derived slots (Phase F, decision D6) -----------------------


ACCT = "a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4"


def test_dynamic_slot_matches_only_legal_names():
    assert sv.is_known_slot(f"mt5.{ACCT}.password") is True
    assert sv.is_known_slot(f"cex.okx.{ACCT}.api_secret") is True
    # A field nothing reads must not be writable, or a typo stores a secret
    # in a slot no consumer will ever look at.
    assert sv.is_known_slot(f"mt5.{ACCT}.passwrod") is False
    assert sv.is_known_slot(f"cex.okx.{ACCT}.secret") is False
    # The catalog still validates unchanged.
    assert sv.is_known_slot("cex.okx.api_key") is True
    assert sv.is_known_slot("nope") is False


def test_dynamic_slot_rejects_non_hex_and_empty_account_id():
    assert sv.is_known_slot("mt5.NOTHEX.password") is False
    assert sv.is_known_slot("mt5..password") is False
    assert sv.is_known_slot("cex.okx..api_key") is False


def test_account_slots_is_single_construction_site():
    slots = sv.account_slots("mt5", ACCT)
    assert slots == {
        "login": f"mt5.{ACCT}.login",
        "password": f"mt5.{ACCT}.password",
        "server": f"mt5.{ACCT}.server",
    }
    cex = sv.account_slots("cex", ACCT, "okx")
    assert cex["api_key"] == f"cex.okx.{ACCT}.api_key"
    with pytest.raises(ValueError):
        sv.account_slots("cex", ACCT)  # venue required
    with pytest.raises(ValueError):
        sv.account_slots("forex", ACCT)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_dynamic_slot_roundtrip_and_isolation(tmp_path):
    v = sv.SecretsVault(data_dir=tmp_path)
    v.set(f"mt5.{ACCT}.password", "acct-one-pw")
    other = "ffffffffffffffffffffffffffffffff"
    v.set(f"mt5.{other}.password", "acct-two-pw")
    assert v.read(f"mt5.{ACCT}.password") == "acct-one-pw"
    assert v.read(f"mt5.{other}.password") == "acct-two-pw"
    assert v.account_slot_status("mt5", ACCT)["password"] is True
    assert v.secrets_leak() is False


def test_dynamic_slots_never_enumerated_by_status(tmp_path):
    """A per-account slot name must not appear on the shared status endpoint."""
    v = sv.SecretsVault(data_dir=tmp_path)
    v.set(f"mt5.{ACCT}.server", "FTTrading-Server")
    st = v.status()
    assert ACCT not in str(st["slots"])


def test_delete_account_slots_removes_every_field(tmp_path):
    v = sv.SecretsVault(data_dir=tmp_path)
    for slot in sv.account_slots("mt5", ACCT).values():
        v.set(slot, "x")
    assert v.delete_account_slots("mt5", ACCT) == 3
    assert v.account_slot_status("mt5", ACCT) == \
        {"login": False, "password": False, "server": False}


def test_vault_status_never_includes_values(tmp_path):
    v = sv.SecretsVault(data_dir=tmp_path)
    v.set("payments.stripe.secret_key", "sk_live_XYZ-secret")
    st = v.status()
    assert st["slots"]["payments.stripe.secret_key"] is True
    assert st["slots"]["cex.okx.demo_api_secret"] is False
    assert "XYZ-secret" not in str(st)


# -- API surface: bootstrap (no identity) ----------------------------------


def test_secrets_status_open_in_bootstrap(client, temp_vault):
    r = client.get("/secrets/status")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body and "persistable" in body
    assert isinstance(body["slots"], dict)


def test_secrets_set_and_delete_in_bootstrap(client, temp_vault):
    value = "bootstrap-enrolled-key-97"
    r = client.put("/secrets/cex.okx.demo_api_secret", json={"value": value})
    assert r.status_code == 200
    assert r.json()["set"] is True
    assert temp_vault.read("cex.okx.demo_api_secret") == value
    assert value not in client.get("/secrets/status").text  # never echoed

    r = client.delete("/secrets/cex.okx.demo_api_secret")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert temp_vault.exists("cex.okx.demo_api_secret") is False


def test_secrets_set_empty_value_400(client, temp_vault):
    r = client.put("/secrets/cex.okx.demo_api_secret", json={"value": ""})
    assert r.status_code == 400


def test_secrets_set_unknown_slot_400(client, temp_vault):
    r = client.put("/secrets/not.a.real.slot", json={"value": "x"})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("unknown vault slot")


# -- API surface: hard gate once an identity exists ------------------------


def test_free_user_403_on_secret_write(client, temp_vault):
    _spawn(client, "free", activate=True)
    r = client.put("/secrets/cex.okx.demo_api_secret",
                   json={"value": "should-not-store"})
    assert r.status_code == 403
    assert "api_access" in r.json()["detail"]
    assert temp_vault.exists("cex.okx.demo_api_secret") is False


def test_pro_user_403_on_secret_write(client, temp_vault):
    _spawn(client, "pro", activate=True)
    r = client.delete("/secrets/cex.okx.demo_api_secret")
    assert r.status_code == 403


def test_institutional_user_enrolls_and_rotates(client, temp_vault):
    _spawn(client, "institutional", activate=True)
    r = client.put("/secrets/cex.okx.demo_api_secret",
                   json={"value": "first"})
    assert r.status_code == 200
    assert temp_vault.read("cex.okx.demo_api_secret") == "first"
    r = client.put("/secrets/cex.okx.demo_api_secret",
                   json={"value": "second"})
    assert r.status_code == 200
    assert r.json()["rotated"] is True
    assert temp_vault.read("cex.okx.demo_api_secret") == "second"


# -- consumers respect the vault --------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_gateway_refresh_applies_rotated_key(temp_vault):
    from execution.cex.gateway import CexGateway
    from core.config import settings
    venue_name = settings.cex.venue
    if venue_name == "okx":
        slot_key = "cex.okx.demo_api_key"     # OKX testnet = dedicated demo slot
    else:
        slot_key = f"cex.{venue_name}.testnet_key"
    g = CexGateway()
    temp_vault.set(slot_key, "ROTATED-VAULT-KEY-77")
    g.refresh()
    assert g._venue._api_key == "ROTATED-VAULT-KEY-77"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_payments_service_refresh_preserves_ledger(temp_vault):
    import governance.payments as pmod
    from governance.payments import PaymentService
    cfg = pmod.settings.payments  # frozen dataclass
    orig_provider = cfg.provider
    try:
        object.__setattr__(cfg, "provider", "stripe")
        svc = PaymentService(mode="sandbox")
        assert svc.wallet("user-none")["balance_usd"] == 0.0
        temp_vault.set("payments.stripe.secret_key", "sk_live_ROTATED")
        svc.refresh_provider()
        assert svc.wallet("user-none")["balance_usd"] == 0.0  # ledger preserved
        assert svc.provider.name == "stripe"
        assert svc.provider.configured() is True
        assert temp_vault.read("payments.stripe.secret_key") == "sk_live_ROTATED"
    finally:
        object.__setattr__(cfg, "provider", orig_provider)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI backend requires Windows")
def test_cex_venue_resolves_key_from_vault(client, temp_vault, monkeypatch):
    monkeypatch.setenv("CEX_OKX_DEMO_API_SECRET", "env-demo-key")
    from execution.cex.venues import OKXVenue
    demo = OKXVenue(mode="testnet")
    assert demo._api_secret == "env-demo-key"
    temp_vault.set("cex.okx.demo_api_secret", "vault-demo-key")
    demo2 = OKXVenue(mode="testnet")
    assert demo2._api_secret == "vault-demo-key"
