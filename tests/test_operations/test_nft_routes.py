"""S7 Strategy NFT + Marketplace routes over the real app (row 782).

Mint is governed and evidence-gated (404 unknown, 409 not-validated); listing is
owner-only (403); a buy settles through the wallet ledger and 402s on overdraft.
"""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.strategy_lab.contracts import PromotionStage  # noqa: E402
from operations.api import app  # noqa: E402


class _Enum:
    def __init__(self, value):
        self.value = value


class _Val:
    tier = "proven"
    score = 0.6


class _FakeAsset:
    def __init__(self, *, stage=PromotionStage.VALIDATED, validation=None,
                 metadata=None):
        self.strategy_id = "s-1"
        self.stage = stage
        self.validation = validation if validation is not None \
            else {"passed": True, "samples": 120, "expected_value": 0.2,
                  "profit_factor": 1.8, "monte_carlo_survival": 0.9,
                  "walkforward_wins": 3, "walkforward_folds": 4}
        self.metadata = metadata or {}
        self.valuation = _Val()
        self.family = _Enum("ict")
        self.asset = "XAUUSD"


class _FakeLayer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    from governance.identity import identity
    from governance.payments import payments_service
    from accounts.strategy_nft import StrategyNFTService, StrategyNFTStore

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    ledger = list(payments_service._ledger)

    def _service():
        return StrategyNFTService(
            store=StrategyNFTStore(str(tmp_path / "nfts.json")))

    def _layer(owner):
        return lambda: _FakeLayer({"s-1": _FakeAsset(metadata={"owner": owner})})

    try:
        yield {"layer": _layer, "service": _service}
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        payments_service._ledger[:] = ledger


def _register(client, monkeypatch, plan="institutional"):
    email = f"nft{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": plan})
    return uid, email


def test_nfts_list_is_read_only_empty(client):
    res = client.get("/economy/nfts")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 0
    assert body["read_only"] is True
    assert body["is_authorisation"] is False


def test_mint_unknown_strategy_is_404(client, monkeypatch, _isolated):
    _register(client, monkeypatch)
    monkeypatch.setattr("operations.api._nft_service", _isolated["service"])
    monkeypatch.setattr("operations.api._asset_layer",
                        lambda: _FakeLayer({}))
    res = client.post("/economy/nfts/mint", json={"strategy_id": "ghost"})
    assert res.status_code == 404


def test_mint_not_validated_is_409(client, monkeypatch, _isolated):
    owner, _ = _register(client, monkeypatch)
    monkeypatch.setattr("operations.api._nft_service", _isolated["service"])

    def layer():
        return _FakeLayer({"s-1": _FakeAsset(stage=PromotionStage.CANDIDATE,
                                             metadata={"owner": owner})})
    monkeypatch.setattr("operations.api._asset_layer", layer)
    res = client.post("/economy/nfts/mint", json={"strategy_id": "s-1"})
    assert res.status_code == 409


def test_full_flow_mint_list_buy(client, monkeypatch, _isolated):
    owner, _ = _register(client, monkeypatch)
    monkeypatch.setattr("operations.api._nft_service", _isolated["service"])
    monkeypatch.setattr("operations.api._asset_layer", _isolated["layer"](owner))

    minted = client.post("/economy/nfts/mint", json={"strategy_id": "s-1"})
    assert minted.status_code == 200, minted.text
    assert minted.json()["minted"] is True
    token_id = minted.json()["token"]["token_id"]

    listed = client.post(f"/economy/nfts/{token_id}/list",
                         json={"price_usd": 100.0})
    assert listed.status_code == 200 and listed.json()["listed"] is True

    # a non-owner cannot list it
    buyer, buyer_email = _register(client, monkeypatch, plan="free")
    assert client.post(f"/economy/nfts/{token_id}/list",
                       json={"price_usd": 1.0}).status_code == 403

    # the buyer needs balance, then acts as themselves
    from governance.payments import payments_service
    payments_service.credit(buyer, 500.0, ref="seed")
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", buyer_email)

    bought = client.post(f"/economy/nfts/{token_id}/buy",
                         json={"buyer": buyer})
    assert bought.status_code == 200, bought.text
    assert bought.json()["sold"] is True
    assert bought.json()["token"]["owner"] == buyer
    assert client.get(f"/payments/wallet/{buyer}").json()["balance_usd"] == 400.0


def test_buy_without_balance_is_402(client, monkeypatch, _isolated):
    owner, _ = _register(client, monkeypatch)
    monkeypatch.setattr("operations.api._nft_service", _isolated["service"])
    monkeypatch.setattr("operations.api._asset_layer", _isolated["layer"](owner))

    token_id = client.post("/economy/nfts/mint",
                           json={"strategy_id": "s-1"}).json()["token"]["token_id"]
    client.post(f"/economy/nfts/{token_id}/list", json={"price_usd": 100.0})

    buyer, buyer_email = _register(client, monkeypatch, plan="free")
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", buyer_email)
    res = client.post(f"/economy/nfts/{token_id}/buy", json={"buyer": buyer})
    assert res.status_code == 402
