"""External Provider Registry domain: repository, seed and adapters.

The separator is the same as the account registry's: what belongs to a *user
record* is ownership-scoped, and what belongs to the *catalog* is public. A
provider is catalog data (row 742), so this file pins the branch points a later
allotter could silently move:

- the `external_providers` table has no `grants_trade_permission`/`may_trade`
  column, asserted by inspection -- absence is a fact, not a docstring;
- a failed lookup raises (fail-closed): an unreachable store is never an empty
  catalog;
- the ForTraders adapter is read-only: `descriptor()`,
  `supported_venues()`, `supported_accounts()`, `verification_requirements()`
  and nothing that returns `True` for "this account may trade";
- seeding is idempotent and remounts ForTraders every boot.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import ExternalProviderRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
)
from providers.fortraders import (  # noqa: E402
    ForTradersProviderAdapter,
)
from providers.seed import (  # noqa: E402
    seed_default_providers,
)


@pytest.fixture
def repo():
    session = bind_test_session()
    session.execute(delete(ExternalProviderRecord))
    session.commit()
    return ExternalProviderRepository(session)


# -- schema ---------------------------------------------------------------


def test_external_providers_table_exists_and_carries_no_fk():
    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    assert "external_providers" in tables
    assert [c for c in ExternalProviderRecord.__table__.columns
            if list(c.foreign_keys)] == []


def test_the_table_never_claims_trade_permission():
    cols = {c.name for c in ExternalProviderRecord.__table__.columns}
    for forbidden in ("grants_trade_permission", "may_trade", "can_trade"):
        assert forbidden not in cols


# -- repository ----------------------------------------------------------


def test_register_then_get_roundtrips(repo):
    repo.register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    fetched = repo.get("fortraders")
    assert fetched["name"] == "ForTraders"
    assert fetched["supported_venues"] == ["mt5"]
    assert fetched["supported_accounts"] == ["challenge", "funded"]
    assert fetched["policy_adapter"] == \
        "providers.fortraders:ForTradersProviderAdapter"


def test_register_is_an_upsert_correction_not_a_duplicate(repo):
    _seed(repo, name="ForTraders")
    assert repo.get("fortraders")["name"] == "ForTraders"
    count = len(repo.list_all())
    assert count == 1


def test_get_unknown_provider_is_none(repo):
    assert repo.get("no-such") is None
    assert repo.get_by_name("no-such") is None


def test_list_all_orders_by_name(repo):
    _seed(repo, provider_id="zeta", name="Zeta")
    _seed(repo, provider_id="alpha", name="Alpha")
    names = [p["name"] for p in repo.list_all()]
    assert names == ["Alpha", "Zeta"]


def test_list_all_filters_by_status(repo):
    _seed(repo, provider_id="on", name="On")
    _seed(repo, provider_id="off", name="Off", status="suspended")
    assert {p["provider_id"] for p in repo.list_all(status="active")} == {"on"}


def test_register_refuses_an_empty_provider_id(repo):
    with pytest.raises(ValueError):
        repo.register(provider_id="", name="Nobody")


def test_register_refuses_an_empty_name(repo):
    with pytest.raises(ValueError):
        repo.register(provider_id="x", name="")


def test_register_refuses_a_non_resolvable_policy_adapter(repo):
    with pytest.raises(ValueError):
        repo.register(provider_id="x", name="X",
                      policy_adapter="not-a-dotted-path")


def test_a_failed_lookup_raises_not_empty_catalog(repo, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "persistence.repositories_accounts.make_live_session", _boom)
    # A repository with NO injected session reaches make_live_session().
    bare = ExternalProviderRepository()
    with pytest.raises(RuntimeError):
        bare.list_all()


def test_delete_removes_a_provider(repo):
    _seed(repo)
    assert repo.delete("fortraders") is True
    assert repo.get("fortraders") is None
    assert repo.delete("fortraders") is False


# -- seed ----------------------------------------------------------------


def test_seed_remounts_fortraders(repo):
    seeded = seed_default_providers(repo=repo)
    assert [p["provider_id"] for p in seeded] == ["fortraders"]
    row = repo.get("fortraders")
    assert row["name"] == "ForTraders"
    assert row["provider_type"] == "funded-prop"
    assert row["referral_program"] == "referral"
    assert row["tracking_method"] == "referral_code"
    assert "grants_trade_permission" not in row


def test_seed_is_idempotent(repo):
    seed_default_providers(repo=repo)
    seed_default_providers(repo=repo)
    assert len(repo.list_all()) == 1


# -- ForTraders adapter --------------------------------------------------


def test_fortraders_adapter_is_a_read_only_probe():
    adapter = ForTradersProviderAdapter()
    desc = adapter.descriptor()
    assert desc["provider_id"] == "fortraders"
    assert desc["name"] == "ForTraders"
    assert desc["supported_venues"] == ["mt5"]
    assert desc["is_authorisation"] is False
    assert desc["read_only"] is True
    assert desc["trade_authority"] == "risk/governor.py"
    assert adapter.supported_venues() == ["mt5"]
    assert "challenge" in adapter.supported_accounts()


def test_verification_requirements_never_claim_a_result():
    adapter = ForTradersProviderAdapter()
    req = adapter.verification_requirements()
    assert req["is_verification_result"] is False
    assert "verified_by" in req
    assert "operator adoption step" in req["verified_by"]


def test_the_adapter_has_no_trade_path():
    adapter = ForTradersProviderAdapter()
    public = {m for m in dir(adapter) if not m.startswith("_")}
    for forbidden in ("authorize", "may_trade", "grants_trade_permission",
                      "place_trade", "approve"):
        assert forbidden not in public


def _seed(repo: ExternalProviderRepository, *, provider_id: str = "fortraders",
          name: str = "ForTraders", status: str = "active"):
    return repo.register(
        provider_id=provider_id, name=name, provider_type="funded-prop",
        referral_program="referral", tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter",
        status=status)
