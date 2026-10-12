"""Evidence Partner registry (S9 ecosystem, partner slice).

The Evidence Plane takes matter from the outside world and the Source Registry
says *where* knowledge may come from; a **partner** is the accountable identity
*behind* a stream of that matter -- the academic group, data vendor, community
or institution that supplies it. These tests pin the properties that keep the
registry honest reference data and never a permission:

- the `evidence_partners` table carries no `grants_trade_permission`/`may_trade`/
  `can_trade` column and no foreign key, asserted by inspection;
- a partner_id must be a canonical slug and a partner needs a name; unknown
  kind/status and a duplicate partner_id are refused (fail-closed onboarding);
- the lifecycle moves only through known statuses, and an unknown partner is a
  distinct refusal;
- attribution is explicit and fail-closed: evidence from an unknown or
  non-active partner is refused, and a registered active partner stamps the
  row; a re-delivery of already-stored matter stays idempotent;
- the summary reports real counts (per kind/status, active, attributed vs
  unattributed evidence) -- never fabricated;
- every outgoing payload carries `is_authorisation: False` and names the Risk
  Governor;
- a store failure raises (fail-closed) -- an outage must not read as "no
  partners were ever registered".
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    EvidencePartnerRecord,
    EvidenceRecord,
    SourceRegistryRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    EvidencePartnerRepository,
    EvidenceRepository,
    SourceRegistryRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.sources.partners import PartnerService  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(EvidenceRecord))
    s.execute(delete(SourceRegistryRecord))
    s.execute(delete(EvidencePartnerRecord))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return EvidencePartnerRepository(session)


@pytest.fixture
def service(session):
    return PartnerService(EvidencePartnerRepository(session))


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


def _valid_fields(**extra):
    fields = {
        "partner_id": "acme-research",
        "name": "Acme Research Group",
        "kind": "academic",
        "status": "active",
        "contact": "research@acme.example",
        "homepage": "https://acme.example",
        "note": "",
    }
    fields.update(extra)
    return fields


# -- the registry is reference data, never a permission ----------------------


def test_partner_table_carries_no_trade_permission_column(session):
    cols = _columns(session, "evidence_partners")
    assert "partner_id" in cols
    for banned in ("grants_trade_permission", "may_trade", "can_trade",
                   "allowed_markets", "trade_authority"):
        assert banned not in cols


def test_partner_table_has_no_foreignkeys(session):
    for fk in inspect(session.get_bind()).get_foreign_keys("evidence_partners"):
        raise AssertionError(f"evidence_partners must not carry FK {fk}")


# -- a partner enters with a canonical slug, or it does not enter ------------


def test_blank_partner_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(partner_id=" "))


def test_space_in_partner_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(partner_id="acme research"))


def test_uppercase_partner_id_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(partner_id="AcmeResearch"))


def test_missing_name_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(name="  "))


def test_unknown_kind_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(kind="blogger"))


def test_unknown_status_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(status="paused"))


def test_duplicate_partner_id_is_refused(repo):
    repo.register(**_valid_fields())
    with pytest.raises(ValueError):
        repo.register(**_valid_fields(name="Acme Research Two"))


# -- reads and the lifecycle --------------------------------------------------


def test_register_then_get(repo):
    row = repo.register(**_valid_fields())
    got = repo.get("acme-research")
    assert got["partner_id"] == "acme-research"
    assert got["name"] == "Acme Research Group"
    assert got["kind"] == "academic"
    assert got["status"] == "active"
    assert row["homepage"] == "https://acme.example"


def test_get_unknown_returns_none(repo):
    assert repo.get("never-registered") is None


def test_list_filters_by_kind_and_status(repo):
    repo.register(**_valid_fields(partner_id="acme-research", kind="academic"))
    repo.register(**_valid_fields(partner_id="quandl-data", kind="data_vendor"))
    repo.register(**_valid_fields(partner_id="r-sig-community", kind="community"))
    assert len(repo.list_all(kind="academic")) == 1
    assert len(repo.list_all(kind="data_vendor")) == 1
    assert len(repo.list_all(status="active")) == 3
    repo.set_status("quandl-data", "retired")
    assert len(repo.list_all(status="retired")) == 1
    with pytest.raises(ValueError):
        repo.list_all(kind="blogger")


def test_set_status_lifecycle_and_unknown(repo):
    repo.register(**_valid_fields())
    assert repo.set_status("acme-research", "suspended")["status"] == "suspended"
    assert repo.get("acme-research")["status"] == "suspended"
    with pytest.raises(ValueError):
        repo.set_status("acme-research", "paused")
    with pytest.raises(ValueError):
        repo.set_status("never-registered", "active")


# -- attribution: real, fail-closed, idempotent ------------------------------


def test_evidence_from_active_partner_is_attributed(session):
    EvidencePartnerRepository(session).register(**_valid_fields())
    plane = EvidencePlaneService(EvidenceRepository(session))
    row = plane.ingest(source_kind="arxiv", payload={"title": "p1"},
                       partner_id="acme-research")
    assert row["is_new"] is True
    assert row["partner_id"] == "acme-research"
    assert EvidenceRepository(session).list_all(
        partner_id="acme-research")[0]["evidence_id"] == row["evidence_id"]


def test_evidence_from_unknown_partner_is_refused(session):
    plane = EvidencePlaneService(EvidenceRepository(session))
    with pytest.raises(ValueError):
        plane.ingest(source_kind="arxiv", payload={"title": "p1"},
                     partner_id="who-dis")


def test_evidence_from_non_active_partner_is_refused(session):
    EvidencePartnerRepository(session).register(**_valid_fields())
    EvidencePartnerRepository(session).set_status("acme-research", "suspended")
    plane = EvidencePlaneService(EvidenceRepository(session))
    with pytest.raises(ValueError):
        plane.ingest(source_kind="arxiv", payload={"title": "p1"},
                     partner_id="acme-research")


def test_partner_less_evidence_stays_unattributed(session):
    plane = EvidencePlaneService(EvidenceRepository(session))
    row = plane.ingest(source_kind="news", payload={"title": "wire"})
    assert row["is_new"] is True
    assert row["partner_id"] == ""


def test_redelivery_is_idempotent_after_partner_retired(session):
    EvidencePartnerRepository(session).register(**_valid_fields())
    plane = EvidencePlaneService(EvidenceRepository(session))
    first = plane.ingest(source_kind="arxiv", payload={"title": "p1"},
                         partner_id="acme-research")
    EvidencePartnerRepository(session).set_status("acme-research", "retired")
    again = plane.ingest(source_kind="arxiv", payload={"title": "p1"},
                         partner_id="acme-research")
    assert again["is_new"] is False
    assert again["evidence_id"] == first["evidence_id"]
    assert again["partner_id"] == "acme-research"


def test_source_registration_carries_partner_attribution(session):
    EvidencePartnerRepository(session).register(**_valid_fields())
    sources = SourceRegistryRepository(session)
    row = sources.register(
        source_id="acme-feed", source_type="academic", provider="Acme",
        kind="arxiv", partner_id="acme-research")
    assert row["partner_id"] == "acme-research"
    assert sources.list_all(partner_id="acme-research")[0]["source_id"] == "acme-feed"
    with pytest.raises(ValueError):
        sources.register(source_id="other-feed", source_type="academic",
                         provider="Other", kind="arxiv", partner_id="who-dis")


# -- the summary reports real counts -----------------------------------------


def test_summary_counts(session):
    partners = EvidencePartnerRepository(session)
    partners.register(**_valid_fields(partner_id="acme-research", kind="academic"))
    partners.register(**_valid_fields(partner_id="quandl-data", kind="data_vendor"))
    SourceRegistryRepository(session).register(
        source_id="acme-feed", source_type="academic", provider="Acme",
        kind="arxiv", partner_id="acme-research")
    plane = EvidencePlaneService(EvidenceRepository(session))
    plane.ingest(source_kind="arxiv", payload={"t": "a"},
                 partner_id="acme-research")
    plane.ingest(source_kind="arxiv", payload={"t": "b"},
                 partner_id="acme-research")
    plane.ingest(source_kind="news", payload={"t": "c"})
    s = PartnerService(partners).summary()
    assert s["total"] == 2
    assert s["per_kind"] == {"academic": 1, "data_vendor": 1}
    assert s["active"] == 2
    assert s["attributed_evidence"] == 2
    assert s["unattributed_evidence"] == 1
    assert s["per_partner"]["acme-research"] == {"evidence": 2, "sources": 1}
    assert s["per_partner"]["quandl-data"] == {"evidence": 0, "sources": 0}


def test_service_payloads_are_never_a_permission(service):
    service.register(**_valid_fields())
    for row in (service.get("acme-research"),
                service.list_all()[0],
                service.set_status("acme-research", "suspended"),
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
        EvidencePartnerRepository().get("any-id")
    with pytest.raises(RuntimeError):
        EvidencePartnerRepository().list_all()
