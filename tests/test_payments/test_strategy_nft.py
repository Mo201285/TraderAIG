"""S7 Strategy NFT + Marketplace module tests (row 782).

Mint is evidence-gated (VALIDATED-or-higher + passing report + recorded owner),
deterministic and idempotent; listing is owner-only with a bounded price; a sale
settles through the one wallet ledger and only then transfers ownership.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from accounts.strategy_nft import StrategyNFTService  # noqa: E402
from governance.payments import build_payment_service  # noqa: E402
from research.strategy_lab.contracts import PromotionStage  # noqa: E402


class _Enum:
    def __init__(self, value):
        self.value = value


class _Val:
    def __init__(self, tier="proven", score=0.6):
        self.tier = tier
        self.score = score


class _FakeAsset:
    def __init__(self, *, stage=PromotionStage.VALIDATED, validation=None,
                 metadata=None, valuation=None, family="ict",
                 asset="XAUUSD", strategy_id="s-1"):
        self.strategy_id = strategy_id
        self.stage = stage
        self.validation = validation
        self.metadata = metadata or {}
        self.valuation = valuation if valuation is not None else _Val()
        self.family = _Enum(family)
        self.asset = asset


class _FakeLayer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


def _report(passed=True):
    return {"passed": passed, "samples": 120, "expected_value": 0.2,
            "profit_factor": 1.8, "monte_carlo_survival": 0.9,
            "walkforward_wins": 3, "walkforward_folds": 4}


def _validated_asset(owner="u1", stage=PromotionStage.VALIDATED, passed=True):
    return _FakeAsset(stage=stage, validation=_report(passed),
                      metadata={"owner": owner})


# ---------------------------------------------------------------------------
# wallet transfer (the settlement primitive)
# ---------------------------------------------------------------------------

def test_transfer_moves_balance_between_wallets():
    svc = build_payment_service()
    svc.credit("buyer", 100.0, ref="seed")
    res = svc.transfer("buyer", "seller", 40.0, ref="p1")
    assert res["settled"] is True
    assert svc.wallet("buyer")["balance_usd"] == 60.0
    assert svc.wallet("seller")["balance_usd"] == 40.0
    assert svc.wallet("seller")["earned_usd"] == 40.0


def test_transfer_refuses_overdraft_and_self():
    svc = build_payment_service()
    svc.credit("buyer", 10.0, ref="seed")
    assert svc.transfer("buyer", "seller", 25.0)["settled"] is False
    assert svc.transfer("buyer", "buyer", 5.0)["settled"] is False
    assert svc.wallet("buyer")["balance_usd"] == 10.0


def test_transfer_is_idempotent_by_ref():
    svc = build_payment_service()
    svc.credit("buyer", 100.0, ref="seed")
    first = svc.transfer("buyer", "seller", 40.0, ref="p1")
    again = svc.transfer("buyer", "seller", 40.0, ref="p1")
    assert first["settled"] is True and again["duplicate"] is True
    assert again["settled"] is False
    assert svc.wallet("buyer")["balance_usd"] == 60.0


# ---------------------------------------------------------------------------
# mint
# ---------------------------------------------------------------------------

def test_mint_requires_validated_or_higher():
    layer = _FakeLayer({"s-1": _validated_asset(stage=PromotionStage.CANDIDATE)})
    out = StrategyNFTService().mint("s-1", asset_layer=layer)
    assert out["minted"] is False and out["reason"] == "not_validated"


def test_mint_requires_a_passing_report():
    layer = _FakeLayer({"s-1": _validated_asset(passed=False)})
    out = StrategyNFTService().mint("s-1", asset_layer=layer)
    assert out["minted"] is False and out["reason"] == "no_passing_validation"


def test_mint_requires_a_recorded_owner():
    layer = _FakeLayer({"s-1": _validated_asset(owner="")})
    out = StrategyNFTService().mint("s-1", asset_layer=layer)
    assert out["minted"] is False and out["reason"] == "no_owner_recorded"


def test_mint_unknown_strategy_is_refused():
    out = StrategyNFTService().mint("ghost", asset_layer=_FakeLayer({}))
    assert out["minted"] is False and out["reason"] == "unknown_strategy"


def test_mint_is_deterministic_and_idempotent():
    svc = StrategyNFTService()
    layer = _FakeLayer({"s-1": _validated_asset()})
    first = svc.mint("s-1", asset_layer=layer)
    assert first["minted"] is True
    token_id = first["token"]["token_id"]
    assert first["token"]["owner"] == "u1"
    assert first["token"]["is_authorisation"] is False

    again = svc.mint("s-1", asset_layer=layer)
    assert again["minted"] is False and again["reason"] == "already_minted"
    assert again["token"]["token_id"] == token_id  # one token for one evidence


# ---------------------------------------------------------------------------
# list / delist / buy
# ---------------------------------------------------------------------------

def _minted_service():
    svc = StrategyNFTService()
    svc.mint("s-1", asset_layer=_FakeLayer({"s-1": _validated_asset()}))
    token_id = svc.all()[0]["token_id"]
    return svc, token_id


def test_only_the_owner_may_list_and_the_price_is_bounded():
    svc, token_id = _minted_service()
    assert svc.list_for_sale(token_id, 100.0, actor="u2")["reason"] == "not_owner"
    assert svc.list_for_sale(token_id, 0.0, actor="u1")["reason"] == "invalid_price"
    assert svc.list_for_sale(token_id, 100.0, actor="u1")["listed"] is True
    assert svc.list_for_sale(token_id, 50.0, actor="u1")["reason"] == "already_listed"


def test_delist_requires_a_listing():
    svc, token_id = _minted_service()
    assert svc.delist(token_id, actor="u1")["reason"] == "not_listed"
    svc.list_for_sale(token_id, 100.0, actor="u1")
    assert svc.delist(token_id, actor="u1")["delisted"] is True
    assert svc.get(token_id)["for_sale"] is False


def test_buy_settles_through_the_wallet_then_transfers_ownership():
    payments = build_payment_service()
    payments.credit("buyer", 500.0, ref="seed")
    svc = StrategyNFTService(payments=payments)
    svc.mint("s-1", asset_layer=_FakeLayer({"s-1": _validated_asset()}))
    token_id = svc.all()[0]["token_id"]
    svc.list_for_sale(token_id, 100.0, actor="u1")

    out = svc.buy(token_id, "buyer")
    assert out["sold"] is True
    assert out["token"]["owner"] == "buyer"
    assert payments.wallet("buyer")["balance_usd"] == 400.0
    assert payments.wallet("u1")["balance_usd"] == 100.0
    # once sold, the listing is gone: a second buy is refused, not re-charged
    again = svc.buy(token_id, "buyer")
    assert again["sold"] is False and again["reason"] == "not_listed"


def test_buy_refuses_overdraft_and_the_owner_buying_their_own_token():
    payments = build_payment_service()  # buyer has zero balance
    svc = StrategyNFTService(payments=payments)
    svc.mint("s-1", asset_layer=_FakeLayer({"s-1": _validated_asset()}))
    token_id = svc.all()[0]["token_id"]
    svc.list_for_sale(token_id, 100.0, actor="u1")

    assert svc.buy(token_id, "u1")["reason"] == "already_owner"
    assert svc.buy(token_id, "buyer")["reason"] == "insufficient_balance"
    assert svc.get(token_id)["owner"] == "u1"  # nothing moved
