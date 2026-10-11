"""Source Registry domain (row 749, RMI-01 slice R1).

The RMI Factory starts with a durable, validated ledger of sources: arXiv,
SSRN, GitHub, macro, market, news, sentiment, internal. The tests pin the
properties that keep it reference data and never a permission:

- the `source_registry` table carries no `grants_trade_permission`/`may_trade`/
  `can_trade` column and no foreign key, asserted by inspection;
- a source_id must be a canonical slug: empty or space-bearing ids are refused,
  so no agent invents a source on the fly;
- unknown source_type/kind/status/cost and an out-of-range reliability are
  refused (fail-closed at registration);
- a duplicate source_id is refused -- the ledger is idempotent reference data;
- reads filter by type, kind and status; `mark_synced` stamps the run; the
  summary reports totals per type/kind plus active/synced counts;
- every outgoing payload carries `is_authorisation: False` and names the Risk
  Governor;
- a store failure raises (fail-closed) -- an outage must not read as "no
  sources were ever registered".
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import SourceRegistryRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    SourceRegistryRepository,
)
from research.sources.registry import SourceRegistryService  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(SourceRegistryRecord))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return SourceRegistryRepository(session)


@pytest.fixture
def service(session):
    return SourceRegistryService(SourceRegistryRepository(session))


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


def _valid_fields(**extra):
    fields = {
        "source_id": "arxiv-ml",
        "source_type": "academic",
        "provider": "arXiv",
        "kind": "arxiv",
        "url_or_feed": "https://export.arxiv.org/oai2",
        "frequency": "daily",
        "reliability": 0.9,
        "cost": "free",
        "status": "active",
        "note": "",
    }
    fields.update(extra)
    return fields


# -- the ledger is reference data, never a permission ------------------------


def test_source_table_carries_no_trade_permission_column(session):
    cols = _columns(session, "source_registry")
    assert "source_id" in cols
    for banned in ("grants_trade_permission", "may_trade", "can_trade",
                   "allowed_markets", "trade_authority"):
        assert banned not in cols


def test_source_table_has_no_foreignkeys(session):
    for fk in inspect(session.get_bind()).get_foreign_keys("source_registry"):
        raise AssertionError(f"source_registry must not carry FK {fk}")


# -- a source enters with a canonical slug, or it does not enter -------------


def test_blank_source_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(source_id=" "))


def test_space_in_source_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(source_id="arxiv ml"))


def test_uppercase_source_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(source_id="ArxivML"))


def test_unknown_source_type_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(source_type="theory"))


def test_unknown_kind_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(kind="twitter"))


def test_unknown_status_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(status="paused"))


def test_unknown_cost_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(cost="negotiable"))


def test_out_of_range_reliability_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(reliability=1.5))


def test_duplicate_source_id_is_refused(repo):
    repo.register(**_valid_fields())
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(url_or_feed="https://second.example"))


# -- reads and the summary ----------------------------------------------------


def test_register_then_get(repo):
    row = repo.register(**_valid_fields())
    got = repo.get("arxiv-ml")
    assert got["source_id"] == "arxiv-ml"
    assert got["source_type"] == "academic"
    assert got["kind"] == "arxiv"
    assert row["provider"] == "arXiv"


def test_get_unknown_returns_none(repo):
    assert repo.get("never-registered") is None


def test_list_filters_by_type_kind_status(repo):
    repo.register(**_valid_fields(source_id="arxiv-ml", source_type="academic",
                                  kind="arxiv"))
    repo.register(**_valid_fields(source_id="github-taig", source_type="code",
                                  kind="github"))
    repo.register(**_valid_fields(source_id="ecb-calendar",
                                  source_type="macro", kind="macro"))
    assert len(repo.list_all(source_type="academic")) == 1
    assert len(repo.list_all(kind="github")) == 1
    assert len(repo.list_all(status="active")) == 3
    repo.set_status("github-taig", "retired")
    assert len(repo.list_all(status="retired")) == 1
    with pytest.raises(ValueError):
        repo.list_all(kind="arithmetic")


def test_update_rejects_unknown_keyword(repo):
    repo.register(**_valid_fields())
    with pytest.raises(TypeError):
        repo.update("arxiv-ml", not_a_field=1)


def test_update_and_mark_synced(repo):
    repo.register(**_valid_fields())
    repo.update("arxiv-ml", reliability=0.95, frequency="weekly")
    updated = repo.get("arxiv-ml")
    assert updated["reliability"] == 0.95
    assert updated["frequency"] == "weekly"
    first = repo.mark_synced("arxiv-ml")
    assert first["last_sync"]
    assert repo.get("arxiv-ml")["last_sync"]


def test_set_status_unknown_is_refused(repo):
    repo.register(**_valid_fields())
    with pytest.raises(ValueError):
        repo.set_status("arxiv-ml", "paused")


def test_summary_counts(repo):
    repo.register(**_valid_fields(source_id="arxiv-ml", source_type="academic",
                                  kind="arxiv"))
    repo.register(**_valid_fields(source_id="github-taig", source_type="code",
                                  kind="github"))
    s = SourceRegistryService(repo).summary()
    assert s["total"] == 2
    assert s["per_type"] == {"academic": 1, "code": 1}
    assert s["per_kind"] == {"arxiv": 1, "github": 1}
    assert s["active"] == 2
    assert s["synced"] == 0


def test_service_payloads_are_never_a_permission(service):
    service.register(**_valid_fields())
    for row in (service.get("arxiv-ml"),
                service.list_all()[0],
                service.update("arxiv-ml", note="x"),
                service.set_status("arxiv-ml", "retired"),
                service.summary()):
        assert row["is_authorisation"] is False
        assert row["trade_authority"] == "risk/governor.py"


# -- fail-closed storage ------------------------------------------------------


def test_store_failure_raises_never_reads_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    with pytest.raises(RuntimeError):
        SourceRegistryRepository().get("any-id")
    with pytest.raises(RuntimeError):
        SourceRegistryRepository().list_all()
