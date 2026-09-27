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
