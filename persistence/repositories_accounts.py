"""Repositories for the Account Registry and Connection Registry.

Session discipline is copied from `ChallengeRepository` and for the same stated
reason: hold a session per call, not for the lifetime of the repository. The pool
is five plus ten, and a repository constructed per request or per test exhausts
it -- which surfaced once already as a silent `durability: false` rather than as
an exception.

The *error* discipline is deliberately the opposite of `ChallengeRepository`'s,
and the difference is the important part.

`ChallengeRepository` swallows store errors because its in-memory copy is the
authority for the running process and the row is only the copy that survives a
restart; failing loudly there would take a 24/7 API down over a disk problem.

An account registry has no in-memory authority. "I could not reach the database,
so this caller owns no accounts" is the only safe reading of a failed lookup, and
every method here therefore either returns a definite answer or raises. There is
no third option of returning an empty list because the store was unreachable: that
one ambiguity is exactly how an accounts endpoint starts reporting "you have no
accounts" for a real user during an outage, and how a cross-tenant read starts
being indistinguishable from an empty one. Callers that must not raise --
request handlers -- get fail-closed behaviour from `accounts.isolation`, which
turns an exception into a denial rather than into an empty result.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import hashlib
import json
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from persistence.db import make_live_session
from persistence.models_accounts import (
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
    EvidencePartnerRecord,
    EvidenceRecord,
    ExternalProviderRecord,
    ExternalReferralEvent,
    PartnerAttestationRecord,
    ProviderWebhookDelivery,
    ReaJobRecord,
    ReferralRecord,
    UserLocaleRecord,
    ResearchMissionRecord,
    ResearchPackageRecord,
    ResearchQueueItemRecord,
    SourceRegistryRecord,
)


# Venues this schema knows how to name. Not a capability list: it exists so an
# account cannot be registered under a misspelled venue that no adapter will ever
# match, which would produce an account that is permanently disconnected while
# looking perfectly valid in the registry.
KNOWN_VENUES = ("mt5", "binance", "okx", "bybit")


# The source families the Evidence Plane recognises (row 746; `news` joins
# with the SSRN/News seams, row 750). Everything the
# external world delivers enters through one of these; `internal` is a label the
# Strategy Lab's own candidates can inherit later, kept honest as "came from
# inside the lab, not from a provider".
KNOWN_SOURCE_KINDS = ("arxiv", "ssrn", "github", "macro", "news", "sentiment",
                      "internal")

# The trust ladder is 0..9 and only moves UP (evidence about the evidence, never
# a permission). 0 = AI idea, 1 = external evidence, 2 = reproducible research,
# 3 = backtest, 4 = walk-forward, 5 = Monte Carlo, 6 = stress test, 7 = paper,
# 8 = governance approval, 9 = production.
MIN_TRUST_LEVEL = 0
MAX_TRUST_LEVEL = 9


def _content_hash(payload: str) -> str:
    return hashlib.sha256(str(payload or "").encode("utf-8")).hexdigest()


_last_delivery_ts = 0.0


def _monotonic_delivery_ts() -> float:
    """A strictly increasing arrival stamp for the delivery log.

    `time.time()` can repeat within a burst (two deliveries land in the same
    microsecond), and the log is ordered by this value -- so an exact tie would
    fall back to a random `delivery_id` and read out of order. Bumping a
    process-local high-water mark guarantees each append is strictly later than
    the last, so a delivery log always reads in the order it was written.
    """
    global _last_delivery_ts
    now = time.time()
    if now <= _last_delivery_ts:
        now = _last_delivery_ts + 1e-6
    _last_delivery_ts = now
    return now


def _row_to_account(row: AccountRecord) -> Dict[str, Any]:
    return {
        "account_id": row.account_id,
        "venue": row.venue,
        "venue_login": row.venue_login,
        "venue_server": row.venue_server,
        "owner_user_id": row.owner_user_id,
        "display_name": row.display_name,
        "venue_currency": row.venue_currency,
        "status": row.status,
        "provider": row.provider,
        "program": row.program,
        "binding_source": row.binding_source,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_connection(row: AccountConnectionRecord) -> Dict[str, Any]:
    return {
        "connection_id": row.connection_id,
        "account_id": row.account_id,
        "connection_kind": row.connection_kind,
        "credential_slot": row.credential_slot,
        "status": row.status,
        "last_connected_at": row.last_connected_at,
        "last_heartbeat_at": row.last_heartbeat_at,
        "last_error": row.last_error,
        "pid": row.pid,
        "port": row.port,
        "instance": row.instance,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class AccountRegistryRepository:
    """Durable registry of accounts and their owners.

    `register()` is an upsert keyed on the venue identity
    `(venue, venue_login, venue_server)` and returns the row, so registering the
    same account twice is a correction rather than a duplicate. It refuses a
    second *owner* for an existing identity instead of silently re-homing the
    account: two operators claiming one login is a conflict to be resolved by a
    person, and an upsert that quietly reassigned ownership would hand one
    operator the positions, ledger and audit trail of another.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    # -- registration ----------------------------------------------------

    def register(self, *, venue: str, venue_login: str, venue_server: str = "",
                 owner_user_id: str, display_name: str = "",
                 venue_currency: str = "USD", provider: str = "", program: str = "",
                 binding_source: str = "") -> Dict[str, Any]:
        """Register an account, or correct the record for an existing one.

        Raises `ValueError` on an unusable input and `PermissionError` when a
        different owner already holds this venue identity. Both are loud on
        purpose: this is an ownership record, and the caller is an operator
        action, not a background sweep that must not fail.
        """
        venue = str(venue or "").strip().lower()
        venue_login = str(venue_login or "").strip()
        venue_server = str(venue_server or "").strip()
        owner_user_id = str(owner_user_id or "").strip()

        if venue not in KNOWN_VENUES:
            raise ValueError(
                f"unknown venue {venue!r}; known venues are {KNOWN_VENUES}")
        if not venue_login:
            raise ValueError("an account needs the venue login it identifies by")
        if not owner_user_id:
            raise ValueError("an account needs an owner; an unowned account has "
                             "no tenancy boundary to enforce")

        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.execute(
                select(AccountRecord).where(
                    AccountRecord.venue == venue,
                    AccountRecord.venue_login == venue_login,
                    AccountRecord.venue_server == venue_server,
                )).scalars().first()

            if row is None:
                row = AccountRecord(
                    account_id=uuid.uuid4().hex,
                    venue=venue,
                    venue_login=venue_login,
                    venue_server=venue_server,
                    owner_user_id=owner_user_id,
                    created_at=now,
                )
                session.add(row)
            elif row.owner_user_id != owner_user_id:
                raise PermissionError(
                    f"account {venue_login}@{venue_server or venue} is already "
                    f"owned by another user ({row.owner_user_id}); re-homing an "
                    f"account is an operator decision, not a registration")

            row.display_name = str(display_name or "")
            row.venue_currency = str(venue_currency or "USD")
            if provider:
                row.provider = str(provider)
            if program:
                row.program = str(program)
            if binding_source:
                row.binding_source = str(binding_source)
            row.updated_at = now
            session.commit()
            return _row_to_account(row)

    # -- lookup ----------------------------------------------------------

    def get(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
        return _row_to_account(row) if row is not None else None

    def get_by_identity(self, venue: str, venue_login: str,
                        venue_server: str = "") -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(AccountRecord).where(
                    AccountRecord.venue == str(venue or "").strip().lower(),
                    AccountRecord.venue_login == str(venue_login or "").strip(),
                    AccountRecord.venue_server == str(venue_server or "").strip(),
                )).scalars().first()
        return _row_to_account(row) if row is not None else None

    def list_for_owner(self, owner_user_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).where(
                    AccountRecord.owner_user_id == str(owner_user_id or "")
                ).order_by(AccountRecord.created_at, AccountRecord.account_id)
            ).scalars().all()
        return [_row_to_account(r) for r in rows]

    def list_all(self) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).order_by(AccountRecord.account_id)
            ).scalars().all()
        return [_row_to_account(r) for r in rows]

    # -- mutation -------------------------------------------------------

    def set_status(self, account_id: str, status: str) -> bool:
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
            if row is None:
                return False
            row.status = str(status or "")
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def delete(self, account_id: str) -> bool:
        """Forget an account's registration.

        Does not cascade to orders, deals or round-trips, and does not delete
        challenge baselines or states. Those rows are an account's trading
        history and its challenge outcome; deleting them because somebody
        removed a registration would destroy the record that says whether the
        account passed. The consistency checker reports the orphans afterwards
        rather than this call hiding them.
        """
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- legacy login indirection ---------------------------------------

    def link_legacy_login(self, account_id: str, venue_login: str,
                          venue_server: str = "") -> None:
        """Bind a pre-registry login to its opaque account id.

        This is the migration seam. `challenge_baselines.account_id` and
        `challenge_states.account_id` are keyed by bare login and are not being
        rewritten, so resolution for those rows goes through here.
        """
        with self._db() as session:
            row = session.get(AccountIdentityRecord, str(account_id or ""))
            if row is None:
                session.add(AccountIdentityRecord(
                    account_id=str(account_id or ""),
                    venue_login=str(venue_login or ""),
                    venue_server=str(venue_server or "")))
            else:
                row.venue_login = str(venue_login or "")
                row.venue_server = str(venue_server or "")
                row.resolved_at = datetime.now(timezone.utc).timestamp()
            session.commit()

    def resolve_legacy_login(self, venue_login: str,
                             venue_server: str = "") -> Optional[str]:
        """Return the account id for a pre-registry login, or None.

        Returns None on a genuine miss *and* on an ambiguous match is avoided by
        construction: the (login, server) pair must match exactly one row, so a
        second registration is caught by `conflicts()` rather than resolved here
        by whichever row the database returned first.
        """
        with self._db() as session:
            rows = session.execute(
                select(AccountIdentityRecord).where(
                    AccountIdentityRecord.venue_login == str(venue_login or ""),
                    AccountIdentityRecord.venue_server == str(venue_server or ""),
                )).scalars().all()
        if len(rows) != 1:
            return None
        return rows[0].account_id


def _validate_provider(payload: Dict[str, Any]) -> None:
    """Refuse a provider row that no adapter could ever match.

    The registry exists so `policy_adapter` paths stay resolvable and a prop
    firm cannot be registered under a misspelled id that every caller will
    fail to find. Identity facts are refused here, never guessed.
    """
    provider_id = str(payload.get("provider_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not provider_id:
        raise ValueError("a provider needs its provider_id")
    if not name:
        raise ValueError("a provider needs a display name")
    adapter = str(payload.get("policy_adapter") or "").strip()
    if adapter and ":" not in adapter:
        raise ValueError(
            f"policy_adapter {adapter!r} must be a dotted path plus class name "
            f"(module.path:ClassName); the registry only stores resolvable names")
    reward = str(payload.get("referral_reward_product") or "").strip()
    if reward:
        # Resolved lazily: the persistence layer must not import the commercial
        # catalogue at module load. The catalogue is the only source of truth
        # for "does this product exist and is it sellable without granting a
        # trade permission" -- a registry row that promised a reward the
        # catalogue cannot honour is a config defect, refused here on purpose.
        try:
            from governance.products import get_product
            product = get_product(reward)
        except Exception:  # noqa: BLE001
            product = None
        if product is None:
            raise ValueError(
                f"referral_reward_product {reward!r} is not in the product "
                f"catalogue; a programme can only reward a sellable service")
        if product.grants_trade_permission:
            raise ValueError(
                f"referral_reward_product {reward!r} claims trade permission; "
                "a commercial reward may never grant trading (rows 741/742/744)")


class ExternalProviderRepository:
    """Durable catalog of external providers (prop firms, brokers, exchanges).

    Mirrors the account registry's discipline: every method returns a definite
    answer **or raises** -- an unreachable store is a loud failure, never an
    empty catalog, because a failed lookup dressed as "no providers" is exactly
    how a UI starts telling an operator the platform has no funded-prop option
    during an outage.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def register(self, *, provider_id: str, name: str,
                 provider_type: str = "", referral_program: str = "",
                 tracking_method: str = "", verification_method: str = "",
                 referral_reward_product: str = "",
                 affiliate_code: str = "", tracking_url: str = "",
                 supported_venues: Optional[List[str]] = None,
                 supported_accounts: Optional[List[str]] = None,
                 policy_adapter: str = "", status: str = "active"
                 ) -> Dict[str, Any]:
        """Record a provider, or correct the catalog entry for an existing one.

        Upsert on `provider_id`. A second registration with a different name is
        a correction rather than a duplicate row -- the catalog is the single
        owner of provider identity, so editing an entry updates it in place.

        `referral_reward_product` is the commercial contract `_validate_provider`
        pins against the product catalogue: a programme may only promise an
        existing, non-trade-granting service as its reward.

        `affiliate_code` / `tracking_url` are the provider's *public* tracking
        coordinates, so a referral link is built from this row rather than pasted
        in a UI. They are marketing facts, not credentials: the webhook signing
        secret lives in the vault (28.18), never here.
        """
        payload = {
            "provider_id": provider_id, "name": name,
            "provider_type": provider_type,
            "referral_program": referral_program,
            "tracking_method": tracking_method,
            "verification_method": verification_method,
            "referral_reward_product": referral_reward_product,
            "supported_venues": supported_venues,
            "supported_accounts": supported_accounts,
            "policy_adapter": policy_adapter, "status": status,
        }
        _validate_provider(payload)

        provider_id = str(provider_id or "").strip()
        name = str(name or "").strip()
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.get(ExternalProviderRecord, provider_id)
            if row is None:
                row = ExternalProviderRecord(
                    provider_id=provider_id, name=name,
                    provider_type=str(provider_type or ""),
                    referral_program=str(referral_program or ""),
                    tracking_method=str(tracking_method or ""),
                    verification_method=str(verification_method or ""),
                    referral_reward_product=str(referral_reward_product or ""),
                    affiliate_code=str(affiliate_code or ""),
                    tracking_url=str(tracking_url or ""),
                    supported_venues=_json_dumps((
                        list(supported_venues) if supported_venues else [])),
                    supported_accounts=_json_dumps((
                        list(supported_accounts) if supported_accounts else [])),
                    policy_adapter=str(policy_adapter or ""),
                    status=str(status or "active"), created_at=now,
                )
                session.add(row)
            else:
                row.name = name
                row.provider_type = str(provider_type or "")
                row.referral_program = str(referral_program or "")
                row.tracking_method = str(tracking_method or "")
                row.verification_method = str(verification_method or "")
                row.referral_reward_product = str(referral_reward_product or "")
                row.affiliate_code = str(affiliate_code or "")
                row.tracking_url = str(tracking_url or "")
                row.supported_venues = _json_dumps((
                    list(supported_venues) if supported_venues else []))
                row.supported_accounts = _json_dumps((
                    list(supported_accounts) if supported_accounts else []))
                row.policy_adapter = str(policy_adapter or "")
                row.status = str(status or "active")
            row.updated_at = now
            session.commit()
            return _row_to_provider(row)

    def get(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ExternalProviderRecord, str(provider_id or ""))
        return _row_to_provider(row) if row is not None else None

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(ExternalProviderRecord).where(
                    ExternalProviderRecord.name == str(name or "").strip()
                )).scalars().first()
        return _row_to_provider(row) if row is not None else None

    def list_all(self, *, status: str = "") -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ExternalProviderRecord)
            if status:
                query = query.where(ExternalProviderRecord.status == str(status))
            rows = session.execute(
                query.order_by(ExternalProviderRecord.name)
            ).scalars().all()
        return [_row_to_provider(r) for r in rows]

    def delete(self, provider_id: str) -> bool:
        with self._db() as session:
            row = session.get(ExternalProviderRecord, str(provider_id or ""))
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


def _json_dumps(values: List[Any]) -> str:
    import json

    return json.dumps(list(values or []))


def _row_to_provider(row: ExternalProviderRecord) -> Dict[str, Any]:
    import json

    def _loads(text: str) -> List[Any]:
        try:
            return json.loads(text or "[]")
        except Exception:  # noqa: BLE001
            return []

    return {
        "provider_id": row.provider_id,
        "name": row.name,
        "provider_type": row.provider_type,
        "referral_program": row.referral_program,
        "tracking_method": row.tracking_method,
        "verification_method": row.verification_method,
        "referral_reward_product": row.referral_reward_product,
        "affiliate_code": row.affiliate_code,
        "tracking_url": row.tracking_url,
        "supported_venues": _loads(row.supported_venues),
        "supported_accounts": _loads(row.supported_accounts),
        "policy_adapter": row.policy_adapter,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_attestation(row: PartnerAttestationRecord) -> Dict[str, Any]:
    import json

    def _loads(text: str) -> List[Any]:
        try:
            return json.loads(text or "[]")
        except Exception:  # noqa: BLE001
            return []

    return {
        "provider_id": row.provider_id,
        "provider_name": row.provider_name,
        "provider_type": row.provider_type,
        "supported_venues": _loads(row.supported_venues),
        "status": row.status,
        "attested_by": row.attested_by,
        "attested_at": row.attested_at,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class PartnerAttestationRepository:
    """Durable operator onboarding attestations for external partners (S11).

    The provider registry (row 743) records *what* an external integration is;
    this records the operator's **adoption act** over it -- who onboarded the
    partner, when and why -- with a lifecycle status (attested / suspended /
    retired). One attestation per `provider_id` (upsert, so a re-attestation
    updates in place). Reads either return a definite answer or raise, so a
    store outage is never dressed as "nothing is attested".
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def attest(self, *, provider_id: str, provider_name: str = "",
               provider_type: str = "", supported_venues: Optional[List[str]] = None,
               attested_by: str = "", note: str = "") -> Dict[str, Any]:
        value = str(provider_id or "").strip()
        if not value:
            raise ValueError("an attestation needs a provider_id")
        actor = str(attested_by or "").strip()
        if not actor:
            raise ValueError("an attestation needs the attesting actor")
        now = datetime.now(timezone.utc).isoformat()
        venues = _json_dumps(list(supported_venues) if supported_venues else [])
        with self._db() as session:
            row = session.get(PartnerAttestationRecord, value)
            if row is None:
                row = PartnerAttestationRecord(
                    provider_id=value,
                    provider_name=str(provider_name or ""),
                    provider_type=str(provider_type or ""),
                    supported_venues=venues,
                    status="attested", attested_by=actor, attested_at=now,
                    note=str(note or "").strip(), created_at=now)
                session.add(row)
            else:
                row.provider_name = str(provider_name or row.provider_name)
                row.provider_type = str(provider_type or row.provider_type)
                row.supported_venues = venues
                row.status = "attested"
                row.attested_by = actor
                row.attested_at = now
                row.note = str(note or "").strip()
            row.updated_at = now
            session.commit()
            return _row_to_attestation(row)

    def get(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(PartnerAttestationRecord, str(provider_id or ""))
        return _row_to_attestation(row) if row is not None else None

    def list_all(self, *, status: str = "") -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(PartnerAttestationRecord)
            if status:
                if status not in ATTESTATION_STATUSES:
                    raise ValueError("unknown attestation status filter")
                query = query.where(PartnerAttestationRecord.status == status)
            rows = session.execute(
                query.order_by(PartnerAttestationRecord.provider_id)
            ).scalars().all()
        return [_row_to_attestation(r) for r in rows]

    def set_status(self, provider_id: str, status: str) -> Dict[str, Any]:
        if status not in ATTESTATION_STATUSES:
            raise ValueError(
                f"unknown attestation status {status!r}; known statuses are "
                f"{', '.join(ATTESTATION_STATUSES)}")
        with self._db() as session:
            row = session.get(PartnerAttestationRecord, str(provider_id or ""))
            if row is None:
                raise ValueError(f"no attestation for provider {provider_id!r}")
            row.status = status
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_attestation(row)


def _row_to_user_locale(row: UserLocaleRecord) -> Dict[str, Any]:
    return {
        "user_id": row.user_id,
        "locale": row.locale,
        "source": row.source,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class UserLocaleRepository:
    """Durable per-user interface locale preference (S12 globalization).

    A preference, not a permission: the row only says which language a surface
    should render in for a user. One row per `user_id` (upsert); the locale
    value is validated by `LocalizationService` against the declared locale
    catalog, so this store stays a faithful record. A read either returns a
    definite row or `None`; the *default* locale is applied by the service, not
    invented here.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(UserLocaleRecord, str(user_id or ""))
        return _row_to_user_locale(row) if row is not None else None

    def set_locale(self, user_id: str, locale: str, *, source: str = "operator",
                   updated_by: str = "") -> Dict[str, Any]:
        value = str(user_id or "").strip()
        if not value:
            raise ValueError("a locale preference needs a user_id")
        locale = str(locale or "").strip()
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.get(UserLocaleRecord, value)
            if row is None:
                row = UserLocaleRecord(
                    user_id=value, locale=locale, source=str(source or "operator"),
                    updated_by=str(updated_by or ""), created_at=now)
                session.add(row)
            else:
                row.locale = locale
                row.source = str(source or "operator")
                row.updated_by = str(updated_by or "")
            row.updated_at = now
            session.commit()
            return _row_to_user_locale(row)

    def list_all(self) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(UserLocaleRecord).order_by(UserLocaleRecord.user_id)
            ).scalars().all()
        return [_row_to_user_locale(r) for r in rows]

    def clear(self, user_id: str) -> bool:
        with self._db() as session:
            row = session.get(UserLocaleRecord, str(user_id or ""))
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


# External referral events (T2 loop): `received -> attributed`, with a separate
# `reward_status` ("" -> "issued" | "failed"). The event is the durable record of
# an external registration arriving under a TrederAIG-issued code; the reward is
# the commercial consequence granted only after the sponsor verifies the
# attribution. Neither ever grants trading (rows 741/742/744/745).
EVENT_RECEIVED = "received"
EVENT_ATTRIBUTED = "attributed"
REWARD_ISSUED = "issued"
REWARD_FAILED = "failed"


def _row_to_event(row: ExternalReferralEvent) -> Dict[str, Any]:
    return {
        "event_id": row.event_id,
        "provider_id": row.provider_id,
        "referral_code": row.referral_code,
        "referral_id": row.referral_id,
        "external_registration_id": row.external_registration_id,
        "channel": row.channel,
        "referred_user_id": row.referred_user_id,
        "account_id": row.account_id,
        "reward_product": row.reward_product,
        "event_status": row.event_status,
        "reward_status": row.reward_status,
        "error_detail": row.error_detail,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_webhook_delivery(row: ProviderWebhookDelivery) -> Dict[str, Any]:
    return {
        "delivery_id": row.delivery_id,
        "provider_id": row.provider_id,
        "channel": row.channel,
        "external_registration_id": row.external_registration_id,
        "referral_code": row.referral_code,
        "event_id": row.event_id,
        "outcome": row.outcome,
        "signature_status": row.signature_status,
        "detail": row.detail,
        "received_at": row.received_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_evidence(row: EvidenceRecord) -> Dict[str, Any]:
    def _loads(raw: str) -> List[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "evidence_id": row.evidence_id,
        "source_kind": row.source_kind,
        "external_id": row.external_id,
        "partner_id": row.partner_id,
        "source_uri": row.source_uri,
        "topic": row.topic,
        "headline": row.headline,
        "content_hash": row.content_hash,
        "relevance": row.relevance,
        "confidence": row.confidence,
        "source_quality": row.source_quality,
        "markets": _loads(row.markets_json),
        "timeframes": _loads(row.timeframes_json),
        "regimes": _loads(row.regimes_json),
        "hypothesis": row.hypothesis,
        "trust_ladder": row.trust_ladder,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_package(row: ResearchPackageRecord) -> Dict[str, Any]:
    def _loads(raw: str) -> List[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "package_id": row.package_id,
        "title": row.title,
        "hypothesis": row.hypothesis,
        "method": row.method,
        "limits": row.limits,
        "evidence_ids": _loads(row.evidence_ids_json),
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# The lifecycle a Research Knowledge Factory package may sign. `recorded` is a
# research index entry delivered by a mission (Paperclip/CrewAI side); `retired`
# is an entry withdrawn by a person. A package NEVER promotes anything -- the
# evidence ladder it cites is the maturity fact, and reading a package is
# reading institutional research reference, never permission (row 748).
PACKAGE_RECORDED = "recorded"
PACKAGE_RETIRED = "retired"

PACKAGE_STATUSES = (PACKAGE_RECORDED, PACKAGE_RETIRED)


def _validate_package_status(status: str) -> str:
    value = str(status or "").strip()
    if value not in PACKAGE_STATUSES:
        raise ValueError(
            f"unknown package status {value!r}; known statuses are "
            f"{', '.join(PACKAGE_STATUSES)}")
    return value


class ResearchPackageRepository:
    """Durable Research Knowledge Factory store (row 748, P3 slice).

    Same family discipline as the rest of the research side: a definite answer
    **or raise**. The lineage invariant is enforced at record time: every cited
    `evidence_id` must name a row that already exists in `evidence_items` --
    a package that cites nothing, or cites an id the plane does not know, is
    fabrication and is refused (fail-closed). Packages are self-contained (no
    ForeignKeys: the evidence side is external and transient, the consistency
    checker couples the tables) and carry no trade-permission column.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def _resolve_evidence(self, session, evidence_ids: List[str]) -> None:
        wanted = sorted({str(e or "").strip() for e in (evidence_ids or [])
                         if str(e or "").strip()})
        if not wanted:
            raise ValueError(
                "a research package may only cite existing evidence; it cites "
                "no evidence at all")
        found = set(session.execute(
            select(EvidenceRecord.evidence_id).where(
                EvidenceRecord.evidence_id.in_(wanted))
        ).scalars().all())
        missing = [e for e in wanted if e not in found]
        if missing:
            raise ValueError(
                "a research package may only cite existing evidence; the cited "
                f"ids do not exist in the plane: {', '.join(missing)}")

    def record(self, *, title: str, evidence_ids: List[str],
               hypothesis: str = "", method: str = "", limits: str = "",
               status: str = PACKAGE_RECORDED, note: str = "") -> Dict[str, Any]:
        """Store one research package whose cited evidence all exists."""
        value = str(title or "").strip()
        if not value:
            raise ValueError("a research package needs a title")
        status = _validate_package_status(status)
        cited = [str(e or "").strip() for e in (evidence_ids or []) if e]
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            self._resolve_evidence(session, cited)
            row = ResearchPackageRecord(
                package_id=uuid.uuid4().hex,
                title=value,
                hypothesis=str(hypothesis or "").strip(),
                method=str(method or "").strip(),
                limits=str(limits or "").strip(),
                evidence_ids_json=json.dumps(sorted(set(cited))),
                status=status,
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_package(row)

    def get(self, package_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ResearchPackageRecord, str(package_id or ""))
        return _row_to_package(row) if row is not None else None

    def list_all(self, *, status: str = "", evidence_id: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ResearchPackageRecord)
            if status:
                query = query.where(
                    ResearchPackageRecord.status == _validate_package_status(status))
            rows = session.execute(
                query.order_by(ResearchPackageRecord.created_at,
                               ResearchPackageRecord.package_id).limit(limit)
            ).scalars().all()
        out = [_row_to_package(r) for r in rows]
        if evidence_id:
            wanted = str(evidence_id or "").strip()
            out = [p for p in out if wanted in p["evidence_ids"]]
        return out

    def summary(self) -> Dict[str, Any]:
        """One call for dashboards: per-status buckets + citation coverage."""
        rows = self.list_all()
        per_status: Dict[str, int] = {}
        cited: set = set()
        for row in rows:
            per_status[row["status"]] = per_status.get(row["status"], 0) + 1
            cited.update(row["evidence_ids"])
        return {
            "total": len(rows),
            "per_status": per_status,
            "cited_evidence_ids": len(cited),
            "known_statuses": list(PACKAGE_STATUSES),
        }


class ReferralEventRepository:
    """Durable record of external registrations under TrederAIG referral codes.

    Same discipline as the rest of the family: a definite answer **or raise**.
    An event store that reported "no registrations" during an outage would let
    a programme believe no one used its codes while the platform was down --
    the fail-closed reading is the only safe one.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def record(self, *, provider_id: str, referral_code: str,
               external_registration_id: str, referral_id: str,
               channel: str = "external", reward_product: str = "",
               note: str = "") -> Dict[str, Any]:
        """Store one external registration event.

        `(provider_id, external_registration_id)` is unique: the same partner
        signup must never arrive as two events, because two events are two
        chances to reward.
        """
        with self._db() as session:
            duplicate = session.execute(
                select(ExternalReferralEvent).where(
                    ExternalReferralEvent.provider_id == str(provider_id or "").strip(),
                    ExternalReferralEvent.external_registration_id
                    == str(external_registration_id or "").strip(),
                )).scalars().first()
            if duplicate is not None:
                raise ValueError(
                    f"registration {external_registration_id!r} for provider "
                    f"{provider_id!r} is already recorded"
                )
            now = datetime.now(timezone.utc).isoformat()
            row = ExternalReferralEvent(
                event_id=uuid.uuid4().hex,
                provider_id=str(provider_id or "").strip(),
                referral_code=str(referral_code or "").strip(),
                referral_id=str(referral_id or "").strip(),
                external_registration_id=str(external_registration_id or "").strip(),
                channel=str(channel or "external").strip(),
                reward_product=str(reward_product or ""),
                event_status=EVENT_RECEIVED,
                note=str(note or ""),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_event(row)

    def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ExternalReferralEvent, str(event_id or ""))
        return _row_to_event(row) if row is not None else None

    def by_referral(self, referral_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(ExternalReferralEvent).where(
                    ExternalReferralEvent.referral_id == str(referral_id or ""))
                .order_by(ExternalReferralEvent.created_at)
            ).scalars().first()
        return _row_to_event(row) if row is not None else None

    def list_all(self, *, status: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ExternalReferralEvent)
            if status:
                query = query.where(
                    ExternalReferralEvent.event_status == str(status))
            rows = session.execute(
                query.order_by(ExternalReferralEvent.created_at,
                               ExternalReferralEvent.event_id).limit(limit)
            ).scalars().all()
        return [_row_to_event(r) for r in rows]

    def attribute(self, event_id: str, referral_id: str, account_id: str,
                  referred_user_id: str) -> Dict[str, Any]:
        """Bind an event to the account whose owner used the code.

        `referred_user_id` is the account registry's recorded owner, exactly the
        no-invented-owner rule the referral attribution enforces.
        """
        with self._db() as session:
            row = session.get(ExternalReferralEvent, str(event_id or ""))
            if row is None:
                raise ValueError("no such registration event")
            if row.event_status != EVENT_RECEIVED:
                raise ValueError(
                    f"event {event_id} is already {row.event_status}; only a "
                    f"received event can be attributed")
            row.referral_id = str(referral_id or "").strip()
            row.account_id = str(account_id or "").strip()
            row.referred_user_id = str(referred_user_id or "").strip()
            row.event_status = EVENT_ATTRIBUTED
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_event(row)

    def set_reward(self, event_id: str, status: str, *,
                   detail: str = "") -> Dict[str, Any]:
        with self._db() as session:
            row = session.get(ExternalReferralEvent, str(event_id or ""))
            if row is None:
                raise ValueError("no such registration event")
            row.reward_status = str(status)
            row.error_detail = str(detail or "")
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_event(row)


class ProviderWebhookDeliveryRepository:
    """Durable record of every inbound partner webhook delivery.

    Where `ReferralEventRepository` stores the *events* a partner reported, this
    stores the *deliveries* that carried them -- accepted or refused. The
    distinction is the point: a forged signature or an unknown code produces no
    event, yet an operator still needs to see that the partner called and what
    went wrong. Every attempt is written, so the seam is observable rather than
    a black hole.

    Same family discipline: a definite answer or raise. A delivery log that
    returned nothing during an outage would read as "the partner never called",
    which is the one reading that must never be guessed.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def record(self, *, provider_id: str, outcome: str, channel: str = "webhook",
               external_registration_id: str = "", referral_code: str = "",
               event_id: str = "", signature_status: str = "",
               detail: str = "") -> Dict[str, Any]:
        """Append one delivery attempt. Always writes, accepted or not."""
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = ProviderWebhookDelivery(
                delivery_id=uuid.uuid4().hex,
                provider_id=str(provider_id or "").strip(),
                channel=str(channel or "webhook").strip(),
                external_registration_id=str(external_registration_id or "").strip(),
                referral_code=str(referral_code or "").strip(),
                event_id=str(event_id or "").strip(),
                outcome=str(outcome or "").strip(),
                signature_status=str(signature_status or "").strip(),
                detail=str(detail or ""),
                received_at=_monotonic_delivery_ts(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_webhook_delivery(row)

    def get(self, delivery_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ProviderWebhookDelivery, str(delivery_id or ""))
        return _row_to_webhook_delivery(row) if row is not None else None

    def list_all(self, *, provider_id: str = "", outcome: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ProviderWebhookDelivery)
            if provider_id:
                query = query.where(
                    ProviderWebhookDelivery.provider_id == str(provider_id))
            if outcome:
                query = query.where(
                    ProviderWebhookDelivery.outcome == str(outcome))
            rows = session.execute(
                query.order_by(ProviderWebhookDelivery.received_at,
                               ProviderWebhookDelivery.delivery_id).limit(limit)
            ).scalars().all()
        return [_row_to_webhook_delivery(r) for r in rows]


class EvidenceRepository:
    """Durable Evidence Plane store (row 746, P1 slice).

    Same family discipline as the rest of the account-side repositories: a
    definite answer **or raise**. A failed lookup must never read as "no
    evidence was ever collected" -- the fail-closed reading is what keeps an
    outage from scrubbing the research record.

    `content_hash` is the dedup key: the same inbound payload (same source,
    same event, same claims) is stored once. `ingest` returns the existing row
    with ``is_new=False`` rather than raising, because an external channel
    re-delivering a paper is not an error -- it is exactly the idempotency the
    n8n-agnostic intake contract requires. `trust_ladder` moves only UP and
    stays within 0..9.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def _validate_kind(self, source_kind: str) -> str:
        kind = str(source_kind or "").strip()
        if kind not in KNOWN_SOURCE_KINDS:
            raise ValueError(
                f"unknown source_kind {kind!r}; known kinds are "
                f"{', '.join(KNOWN_SOURCE_KINDS)}")
        return kind

    def _validate_trust(self, trust_ladder: int) -> int:
        try:
            level = int(trust_ladder)
        except (TypeError, ValueError):
            raise ValueError("trust_ladder must be an integer 0..9")
        if not (MIN_TRUST_LEVEL <= level <= MAX_TRUST_LEVEL):
            raise ValueError(
                f"trust_ladder {level} is outside 0..9; a level labels evidence "
                f"maturity, it never grants authority")
        return level

    def ingest(self, *, content_hash: str, source_kind: str,
               external_id: str = "", source_uri: str = "", topic: str = "",
               headline: str = "", relevance: Optional[float] = None,
               confidence: Optional[float] = None,
               source_quality: Optional[float] = None,
               markets: Optional[List[str]] = None,
               timeframes: Optional[List[str]] = None,
               regimes: Optional[List[str]] = None,
               hypothesis: str = "", trust_ladder: int = MIN_TRUST_LEVEL,
               partner_id: str = "", note: str = "") -> Dict[str, Any]:
        """Store one evidence item, or return the identical stored one.

        Returns ``{**row, "is_new": bool}``. Uniqueness is content-based, so a
        re-delivery is idempotent -- the intake contract n8n works against.
        When ``partner_id`` is given it must name an *active* registered
        partner (fail-closed): external matter is attributed to an accountable
        provider, never to a name nobody vouched for.
        """
        kind = self._validate_kind(source_kind)
        level = self._validate_trust(trust_ladder)
        digest = _content_hash(content_hash)
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            existing = session.execute(
                select(EvidenceRecord).where(
                    EvidenceRecord.content_hash == digest)
            ).scalars().first()
            if existing is not None:
                return {**_row_to_evidence(existing), "is_new": False}
            pid = _resolve_partner(session, partner_id)
            row = EvidenceRecord(
                evidence_id=uuid.uuid4().hex,
                source_kind=kind,
                external_id=str(external_id or "").strip(),
                partner_id=pid,
                source_uri=str(source_uri or ""),
                topic=str(topic or "").strip(),
                headline=str(headline or ""),
                content_hash=digest,
                relevance=relevance,
                confidence=confidence,
                source_quality=source_quality,
                markets_json=json.dumps(list(markets or []), sort_keys=True),
                timeframes_json=json.dumps(list(timeframes or []), sort_keys=True),
                regimes_json=json.dumps(list(regimes or []), sort_keys=True),
                hypothesis=str(hypothesis or ""),
                trust_ladder=level,
                note=str(note or ""),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return {**_row_to_evidence(row), "is_new": True}

    def get(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(EvidenceRecord, str(evidence_id or ""))
        return _row_to_evidence(row) if row is not None else None

    def list_all(self, *, source_kind: str = "", topic: str = "",
                 market: str = "", regime: str = "",
                 partner_id: str = "",
                 min_trust: Optional[int] = None,
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(EvidenceRecord)
            if source_kind:
                query = query.where(
                    EvidenceRecord.source_kind == self._validate_kind(source_kind))
            if topic:
                query = query.where(EvidenceRecord.topic == str(topic).strip())
            if partner_id:
                query = query.where(
                    EvidenceRecord.partner_id == str(partner_id).strip())
            if min_trust is not None:
                level = self._validate_trust(min_trust)
                query = query.where(EvidenceRecord.trust_ladder >= level)
            rows = session.execute(
                query.order_by(EvidenceRecord.created_at,
                               EvidenceRecord.evidence_id).limit(limit)
            ).scalars().all()
        out = []
        for row in rows:
            item = _row_to_evidence(row)
            if market and market not in item["markets"]:
                continue
            if regime and regime not in item["regimes"]:
                continue
            out.append(item)
        return out

    def classify(self, evidence_id: str, *, relevance: Optional[float],
                 confidence: Optional[float], source_quality: Optional[float],
                 markets: Optional[List[str]],
                 timeframes: Optional[List[str]],
                 regimes: Optional[List[str]], hypothesis: str) -> Dict[str, Any]:
        """Attach the structured reading a later research stage will consume."""
        with self._db() as session:
            row = session.get(EvidenceRecord, str(evidence_id or ""))
            if row is None:
                raise ValueError("no such evidence item")
            if relevance is not None:
                row.relevance = float(relevance)
            if confidence is not None:
                row.confidence = float(confidence)
            if source_quality is not None:
                row.source_quality = float(source_quality)
            if markets is not None:
                row.markets_json = json.dumps(list(markets), sort_keys=True)
            if timeframes is not None:
                row.timeframes_json = json.dumps(list(timeframes), sort_keys=True)
            if regimes is not None:
                row.regimes_json = json.dumps(list(regimes), sort_keys=True)
            if hypothesis is not None:
                row.hypothesis = str(hypothesis or "")
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_evidence(row)

    def advance_trust(self, evidence_id: str, level: int) -> Dict[str, Any]:
        """Move a claim UP the maturity ladder. Downward moves are refused."""
        target = self._validate_trust(level)
        with self._db() as session:
            row = session.get(EvidenceRecord, str(evidence_id or ""))
            if row is None:
                raise ValueError("no such evidence item")
            if target < row.trust_ladder:
                raise ValueError(
                    f"trust ladder is monotonic: {row.trust_ladder} cannot go "
                    f"down to {target}")
            row.trust_ladder = target
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_evidence(row)


# Referral attribution lifecycle. `pending` is an issued code, `attributed` is a
# code whose account has been linked, `verified` is a code whose purchase was
# confirmed, and `declined` is a code that was never used or was rejected. A
# verified attribution is final.
REFERRAL_PENDING = "pending"
REFERRAL_ATTRIBUTED = "attributed"
REFERRAL_VERIFIED = "verified"
REFERRAL_DECLINED = "declined"

REFERRAL_STATUSES = (REFERRAL_PENDING, REFERRAL_ATTRIBUTED,
                     REFERRAL_VERIFIED, REFERRAL_DECLINED)


def _validate_referral(payload: Dict[str, Any], provider: Optional[Dict[str, Any]]) -> None:
    """Refuse a referral that no provider programme could ever honour.

    Identity facts are refused here, never guessed: a referral names a specific
    code, a specific sponsor and a specific provider programme, and an empty
    one cannot be stored as a claim about nothing.
    """
    provider_id = str(payload.get("provider_id") or "").strip()
    code = str(payload.get("referral_code") or "").strip()
    owner = str(payload.get("owner_user_id") or "").strip()
    if not provider_id:
        raise ValueError("a referral needs the provider it is issued against")
    if not code:
        raise ValueError("a referral needs its code")
    if not owner:
        raise ValueError("a referral needs the user who sponsors it")
    if provider is None:
        raise ValueError(
            f"provider {provider_id!r} is not in the external provider registry; "
            "a referral may only be issued against a registered provider")
    if not str(provider.get("referral_program") or "").strip():
        raise ValueError(
            f"provider {provider_id!r} has no referral programme; a referral may "
            "only be issued against a programme that is registered as one")


def _row_to_referral(row: ReferralRecord) -> Dict[str, Any]:
    return {
        "referral_id": row.referral_id,
        "provider_id": row.provider_id,
        "referral_code": row.referral_code,
        "owner_user_id": row.owner_user_id,
        "account_id": row.account_id,
        "referred_user_id": row.referred_user_id,
        "tracking_method": row.tracking_method,
        "verification_method": row.verification_method,
        "attribution_status": row.attribution_status,
        "verified_at": row.verified_at,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class ReferralRepository:
    """Durable record of which account originated from which referral code.

    Ownership and the referral state machine are enforced here rather than
    trusted to a caller: `issue()` refuses a code against a provider that has no
    registered programme, `attribute()` verifies the account belongs to the
    person being referred, and `verify()` only ever fires on an *attributed*
    code -- there is no path that marks a code verified without an account
    attached to it.

    The error discipline mirrors the account registry: every method returns a
    definite answer **or raises**, because a referral ledger that reports "no
    attributions" while the store is down would let a programme bill for
    sourcing nobody can prove. Fail-closed is the only safe reading.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def issue(self, *, provider_id: str, referral_code: str,
              owner_user_id: str, note: str = "") -> Dict[str, Any]:
        """Create a pending referral code against a provider programme.

        Snapshots the provider's tracking/verification contract at issue time so
        an old code always says how it was tracked, even after the registry row
        is edited. A second code with the same provider+code is refused: one
        code cannot mean two issuances.
        """
        provider_id = str(provider_id or "").strip()
        payload = {"provider_id": provider_id,
                   "referral_code": referral_code, "owner_user_id": owner_user_id}
        with self._db() as session:
            provider = ExternalProviderRepository(session).get(provider_id)
            _validate_referral(payload, provider)
            duplicate = session.execute(
                select(ReferralRecord).where(
                    ReferralRecord.provider_id == provider_id,
                    ReferralRecord.referral_code == str(referral_code or "").strip(),
                )).scalars().first()
            if duplicate is not None:
                raise ValueError(
                    f"referral code {referral_code!r} already exists for "
                    f"provider {provider_id!r}; a code is unique within a "
                    f"programme")
            now = datetime.now(timezone.utc).isoformat()
            row = ReferralRecord(
                referral_id=uuid.uuid4().hex,
                provider_id=provider_id,
                referral_code=str(referral_code or "").strip(),
                owner_user_id=str(owner_user_id or "").strip(),
                tracking_method=str(provider.get("tracking_method") or ""),
                verification_method=str(provider.get("verification_method") or ""),
                attribution_status=REFERRAL_PENDING,
                note=str(note or ""),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_referral(row)

    def get(self, referral_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ReferralRecord, str(referral_id or ""))
        return _row_to_referral(row) if row is not None else None

    def get_by_code(self, provider_id: str,
                    referral_code: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(ReferralRecord).where(
                    ReferralRecord.provider_id == str(provider_id or "").strip(),
                    ReferralRecord.referral_code == str(referral_code or "").strip(),
                )).scalars().first()
        return _row_to_referral(row) if row is not None else None

    def list_for_owner(self, owner_user_id: str, *, status: str = "",
                       limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ReferralRecord).where(
                ReferralRecord.owner_user_id == str(owner_user_id or "").strip())
            if status:
                query = query.where(
                    ReferralRecord.attribution_status == str(status))
            rows = session.execute(
                query.order_by(ReferralRecord.created_at,
                               ReferralRecord.referral_id).limit(limit)
            ).scalars().all()
        return [_row_to_referral(r) for r in rows]

    def list_for_account(self, account_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(ReferralRecord).where(
                    ReferralRecord.account_id == str(account_id or ""))
                .order_by(ReferralRecord.created_at)
            ).scalars().all()
        return [_row_to_referral(r) for r in rows]

    def list_by_provider(self, provider_id: str, *, status: str = "",
                         limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ReferralRecord).where(
                ReferralRecord.provider_id == str(provider_id or "").strip())
            if status:
                query = query.where(
                    ReferralRecord.attribution_status == str(status))
            rows = session.execute(
                query.order_by(ReferralRecord.created_at,
                               ReferralRecord.referral_id).limit(limit)
            ).scalars().all()
        return [_row_to_referral(r) for r in rows]

    def list_all(self, *, status: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ReferralRecord)
            if status:
                query = query.where(
                    ReferralRecord.attribution_status == str(status))
            rows = session.execute(
                query.order_by(ReferralRecord.created_at,
                               ReferralRecord.referral_id).limit(limit)
            ).scalars().all()
        return [_row_to_referral(r) for r in rows]

    # -- attribution lifecycle -----------------------------------------

    def attribute(self, referral_id: str, account_id: str,
                  referred_user_id: str = "", note: str = "") -> Dict[str, Any]:
        """Link an account to a pending referral code.

        The account's recorded owner IS the referred person; an attribution
        that named a different `referred_user_id` would be a second source of
        truth about who owns the account, so it is refused rather than stored.
        This only fires on a `pending` code and only on an account that is not
        already attributed for the same provider -- the two uniqueness rules
        the schema enforces, surfaced here as readable refusals.
        """
        account_id = str(account_id or "").strip()
        if not account_id:
            raise ValueError("attribute needs the account being attributed")
        with self._db() as session:
            row = session.get(ReferralRecord, str(referral_id or ""))
            if row is None:
                raise ValueError("no such referral; an attribution needs a "
                                 "referral that exists")
            if row.attribution_status != REFERRAL_PENDING:
                raise ValueError(
                    f"referral {row.referral_id} is already "
                    f"{row.attribution_status}; only a pending code can be "
                    f"attributed")
            account = AccountRegistryRepository(session).get(account_id)
            if account is None:
                raise ValueError(
                    f"account {account_id!r} is not in the account registry; an "
                    "attribution needs an account that exists")
            actual_owner = str(account.get("owner_user_id") or "")
            claimed = str(referred_user_id or "").strip()
            if claimed and claimed != actual_owner:
                raise ValueError(
                    f"account {account_id} belongs to {actual_owner or 'nobody'}, "
                    f"not {claimed}; the account's owner is the referred person")
            existing = session.execute(
                select(ReferralRecord).where(
                    ReferralRecord.provider_id == row.provider_id,
                    ReferralRecord.account_id == account_id)).scalars().first()
            if existing is not None and existing.referral_id != row.referral_id:
                raise ValueError(
                    f"account {account_id} is already attributed to referral "
                    f"{existing.referral_id} for provider {row.provider_id}; one "
                    "account has one origin per provider")
            row.account_id = account_id
            row.referred_user_id = actual_owner
            row.attribution_status = REFERRAL_ATTRIBUTED
            if note:
                row.note = str(note)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_referral(row)

    def verify(self, referral_id: str, note: str = "") -> Dict[str, Any]:
        """Confirm a purchase for an *attributed* code. Final.

        Verification is the provider-confirmation step (P2 hook): it may only
        fire once the code has an account, and it may never fire twice. A code
        with no account cannot be verified, because there is nothing to confirm
        a purchase *for*.
        """
        with self._db() as session:
            row = session.get(ReferralRecord, str(referral_id or ""))
            if row is None:
                raise ValueError("no such referral")
            if row.attribution_status != REFERRAL_ATTRIBUTED:
                raise ValueError(
                    f"referral {row.referral_id} is {row.attribution_status}; "
                    "only an attributed code can be verified (a purchase is "
                    "confirmed for an account, not for a code)")
            row.attribution_status = REFERRAL_VERIFIED
            row.verified_at = datetime.now(timezone.utc).timestamp()
            if note:
                row.note = str(note)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_referral(row)

    def decline(self, referral_id: str, note: str = "") -> Dict[str, Any]:
        """Refuse or cancel a pending/attributed code. Never touches verified.

        The sanctioned way to remove an unwanted code: a declined row is still a
        row, so a programme can see that sourcing was refused rather than never
        logged. A verified attribution is a confirmed fact and is deliberately
        not reversible by this call.
        """
        with self._db() as session:
            row = session.get(ReferralRecord, str(referral_id or ""))
            if row is None:
                raise ValueError("no such referral")
            if row.attribution_status == REFERRAL_VERIFIED:
                raise ValueError(
                    f"referral {row.referral_id} is verified; a confirmed "
                    "attribution is not declined, it stays provable")
            row.attribution_status = REFERRAL_DECLINED
            if note:
                row.note = str(note)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_referral(row)

    def delete(self, referral_id: str) -> bool:
        """Forget a code that was never attributed.

        Only a `pending` code can be removed. An attributed or declined code is
        a provenance row (something was asserted about an account, or a refusal
        was logged), and silently removing either would erase how an account got
        attributed; the sanctioned removal of an unwanted code is a `decline`.
        """
        with self._db() as session:
            row = session.get(ReferralRecord, str(referral_id or ""))
            if row is None:
                return False
            if row.attribution_status != REFERRAL_PENDING:
                raise ValueError(
                    f"referral {row.referral_id} is {row.attribution_status}; "
                    "only a pending code can be deleted (decline it instead)")
            session.delete(row)
            session.commit()
            return True


class AccountConnectionRepository:
    """Durable record of how each account is reached."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def register(self, *, account_id: str, connection_kind: str,
                 credential_slot: str = "") -> Dict[str, Any]:
        """Declare a route to an account. Upsert on (account, kind).

        `credential_slot` is a SecretsVault slot *name*. There is no code path
        here that stores a credential, by design.
        """
        account_id = str(account_id or "").strip()
        connection_kind = str(connection_kind or "").strip()
        if not account_id:
            raise ValueError("a connection needs the account it connects to")
        if not connection_kind:
            raise ValueError("a connection needs a kind (mt5_terminal, cex_rest, "
                             "cex_ws)")

        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == account_id,
                    AccountConnectionRecord.connection_kind == connection_kind,
                )).scalars().first()
            if row is None:
                row = AccountConnectionRecord(
                    connection_id=uuid.uuid4().hex,
                    account_id=account_id,
                    connection_kind=connection_kind,
                    credential_slot=str(credential_slot or ""),
                    created_at=now,
                )
                session.add(row)
            elif credential_slot:
                row.credential_slot = str(credential_slot)
            row.updated_at = now
            session.commit()
            return _row_to_connection(row)

    def get(self, account_id: str, connection_kind: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
        return _row_to_connection(row) if row is not None else None

    def list_for_account(self, account_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or "")
                ).order_by(AccountConnectionRecord.connection_kind)
            ).scalars().all()
        return [_row_to_connection(r) for r in rows]

    def set_status(self, account_id: str, connection_kind: str, status: str,
                   *, last_error: Optional[str] = None) -> bool:
        """Record reachability, and when it was last true.

        `last_connected_at` is only advanced on a connected status. Writing it
        on every status change would let a failed reconnect refresh the timestamp
        that says the account has been reachable, and that timestamp is what an
        operator reads to decide whether a stale feed is a market that has gone
        quiet or a link that has been down for a week.
        """
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            row.status = str(status or "")
            if str(status or "").lower() in ("connected", "live", "ok"):
                row.last_connected_at = now
            if last_error is not None:
                row.last_error = str(last_error)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def heartbeat(self, account_id: str, connection_kind: str) -> bool:
        """Refresh liveness only. Never changes status.

        Deliberately not a status write: a heartbeat says the socket is alive, and
        a link that is alive but degraded is still `degraded`, so folding the two
        into one field would erase the distinction an operator needs.
        """
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            row.last_heartbeat_at = datetime.now(timezone.utc).timestamp()
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def delete(self, account_id: str, connection_kind: str) -> bool:
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- engine runtime (Phase F5) ---------------------------------------
    #
    # The three methods below are the durable half of the AccountSupervisor.
    # They record which OS process serves a connection and on which port, and
    # they can be read back after a restart to reconcile a worker whose process
    # is gone. They are deliberately separate from `set_status`: a process can be
    # recorded as `pid=P` while its connection status is still `disconnected`
    # (P just spawned, not yet connected), and collapsing the two would make
    # "started" and "reachable" the same claim.

    def set_runtime(self, account_id: str, connection_kind: str, *,
                    pid: Optional[int] = None, port: Optional[int] = None,
                    instance: Optional[str] = None,
                    status: Optional[str] = None) -> bool:
        """Record (or refresh) the engine process for a connection.

        Only the fields passed are written, so a heartbeat that carries a new
        `last_heartbeat_at` need not restate the pid, and clearing the pid
        (`clear_runtime`) is a distinct operation from lowering the status.
        """
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            if pid is not None:
                row.pid = int(pid)
            if port is not None:
                row.port = int(port)
            if instance is not None:
                row.instance = str(instance)
            if status is not None:
                row.status = str(status)
                if str(status).lower() in ("connected", "live", "ok"):
                    row.last_connected_at = now
            row.last_heartbeat_at = now
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def clear_runtime(self, account_id: str, connection_kind: str, *,
                      status: str = "disconnected",
                      last_error: Optional[str] = None) -> bool:
        """Forget the engine process for a connection, honestly.

        Nulls the runtime columns rather than leaving a dead pid behind: a row
        that still names a process is a row a reconciliation pass will try to
        adopt, and adopting a pid that has been reused by an unrelated process
        is exactly the failure this column is meant to prevent.
        """
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            row.pid = None
            row.port = None
            row.instance = None
            row.status = str(status or "disconnected")
            if last_error is not None:
                row.last_error = str(last_error)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def list_running(self, *, connection_kind: str = "") -> List[Dict[str, Any]]:
        """Every connection that names a live engine process.

        Filtered on `pid IS NOT NULL`, which is the one durable fact that says a
        worker was last recorded as running -- not on status, because an engine
        whose terminal dropped is still a running process holding a port.
        """
        with self._db() as session:
            stmt = select(AccountConnectionRecord).where(
                AccountConnectionRecord.pid.is_not(None))
            if connection_kind:
                stmt = stmt.where(
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind))
            rows = session.execute(
                stmt.order_by(AccountConnectionRecord.created_at)).scalars().all()
        return [_row_to_connection(r) for r in rows]


class AccountConsistencyChecker:
    """Reports referential problems the schema deliberately does not prevent.

    `persistence/models_accounts.py` documents why there are no foreign keys here,
    which only works if something is actually checking. This is that something,
    and it returns a report rather than raising: an operator needs to see all of
    the drift at once, and a repair job that dies on the first orphan is a repair
    job that fixes one row per run.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def orphaned_connections(self) -> List[Dict[str, Any]]:
        """Connections whose account no longer exists."""
        with self._db() as session:
            rows = session.execute(
                select(AccountConnectionRecord)
                .where(AccountConnectionRecord.account_id.not_in(
                    select(AccountRecord.account_id)))
                .order_by(AccountConnectionRecord.account_id)
            ).scalars().all()
        return [{"connection_id": r.connection_id, "account_id": r.account_id,
                 "connection_kind": r.connection_kind,
                 "credential_slot": r.credential_slot, "status": r.status}
                for r in rows]

    def identity_conflicts(self) -> List[Dict[str, Any]]:
        """Logins that resolve to more than one account.

        Any row here means `resolve_legacy_login()` is returning None for that
        login -- i.e. the indirection is refusing to guess, and the affected
        challenge rows have no resolved account until an operator picks one.
        """
        with self._db() as session:
            rows = session.execute(
                select(
                    AccountIdentityRecord.venue_login,
                    AccountIdentityRecord.venue_server,
                    func.count(AccountIdentityRecord.account_id),
                )
                .group_by(
                    AccountIdentityRecord.venue_login,
                    AccountIdentityRecord.venue_server,
                )
                .having(func.count(AccountIdentityRecord.account_id) > 1)
            ).all()
        return [{"venue_login": r[0], "venue_server": r[1], "account_count": int(r[2])}
                for r in rows]

    def unowned_accounts(self) -> List[Dict[str, Any]]:
        """Accounts whose owner is not a known user.

        Expected to be empty: `register()` requires an owner. Reported anyway,
        because a row can only reach that state by an out-of-band insert, and an
        account nobody owns is an account nobody is accountable for.
        """
        from persistence.models import UserRecord

        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).where(
                    AccountRecord.owner_user_id.not_in(
                        select(UserRecord.user_id))
                ).order_by(AccountRecord.account_id)
            ).scalars().all()
        return [{"account_id": r.account_id, "venue": r.venue,
                 "venue_login": r.venue_login, "owner_user_id": r.owner_user_id}
                for r in rows]

    def orphaned_bindings(self) -> List[Dict[str, Any]]:
        """Strategy bindings whose account no longer exists.

        The mirror of `orphaned_connections`. Expected to be empty, and reported
        for the same reason: there is no foreign key holding this row to an
        account, so a deleted account leaves a binding that still reads as a
        permission to somebody who queries only this table.
        """
        from persistence.models_trades import AccountStrategyBindingRecord

        with self._db() as session:
            rows = session.execute(
                select(AccountStrategyBindingRecord)
                .where(AccountStrategyBindingRecord.account_id.not_in(
                    select(AccountRecord.account_id)))
                .order_by(AccountStrategyBindingRecord.account_id)
            ).scalars().all()
        return [{"binding_id": r.binding_id, "account_id": r.account_id,
                 "strategy_id": r.strategy_id, "variant_hash": r.variant_hash,
                 "status": r.status} for r in rows]

    def orphaned_referrals(self) -> List[Dict[str, Any]]:
        """Referrals that point at a provider, an account or a sponsor that is
        no longer a known row.

        There is no foreign key between `referrals` and either `external_providers`
        or `accounts` (the account-family rule), so a provider that was de-listed
        or an account that was deleted leaves a referral that still claims
        sourcing. Attribution is provenance, so the survivor is reported rather
        than silently dropped.

        An unattributed referral appears here only when its provider or its
        sponsor is unknown; an attributed one is checked against all three.
        """
        from persistence.models import UserRecord

        with self._db() as session:
            rows = session.execute(
                select(ReferralRecord).order_by(ReferralRecord.created_at)
            ).scalars().all()
            report_rows = []
            for r in rows:
                kinds = []
                if session.get(ExternalProviderRecord, r.provider_id) is None:
                    kinds.append("unknown_provider")
                if r.account_id and session.get(AccountRecord, r.account_id) is None:
                    kinds.append("unknown_account")
                if session.get(UserRecord, r.owner_user_id) is None:
                    kinds.append("unknown_sponsor")
                if kinds:
                    report_rows.append({
                        "referral_id": r.referral_id,
                        "provider_id": r.provider_id,
                        "account_id": r.account_id,
                        "owner_user_id": r.owner_user_id,
                        "attribution_status": r.attribution_status,
                        "kinds": kinds,
                    })
        return report_rows

    def orphaned_referral_events(self) -> List[Dict[str, Any]]:
        """Events whose provider, code or attributed account is no longer known.

        Kept as a checkable surface because an event is a commercial promise:
        a provider that vanishes from the registry with received events still
        on disk would otherwise let a registration that was never attributed
        (and never rewarded) disappear without a trace. The survivor is
        reported rather than silently dropped, with the same no-foreign-key
        discipline as `orphaned_referrals`.
        """
        with self._db() as session:
            rows = session.execute(
                select(ExternalReferralEvent).order_by(
                    ExternalReferralEvent.created_at)
            ).scalars().all()
            report_rows = []
            for r in rows:
                kinds = []
                if session.get(ExternalProviderRecord, r.provider_id) is None:
                    kinds.append("unknown_provider")
                if r.referral_id and session.get(ReferralRecord, r.referral_id) is None:
                    kinds.append("unknown_referral")
                if r.account_id and session.get(AccountRecord, r.account_id) is None:
                    kinds.append("unknown_account")
                if kinds:
                    report_rows.append({
                        "event_id": r.event_id,
                        "provider_id": r.provider_id,
                        "referral_code": r.referral_code,
                        "referral_id": r.referral_id,
                        "account_id": r.account_id,
                        "event_status": r.event_status,
                        "reward_status": r.reward_status,
                        "kinds": kinds,
                    })
        return report_rows

    def evidence_drift(self) -> List[Dict[str, Any]]:
        """Evidence rows that violate the plane's own invariants.

        An evidence row is self-contained (no foreign keys), so the drift worth
        checking is the schema's meaning: an unknown `source_kind`, or a
        `content_hash` that is missing/malformed, or a `trust_ladder` outside
        0..9. A ladder level labels evidence maturity and never grants
        authority (row 746); out-of-band inserts are the only way to reach
        these states, and the survivor is reported, not silently accepted. A
        duplicated `content_hash` cannot occur while the column stays UNIQUE,
        so it is not checked here -- a checker that reports an impossible
        state is a checker nobody can trust.
        """
        report_rows = []
        with self._db() as session:
            rows = session.execute(
                select(EvidenceRecord).order_by(EvidenceRecord.created_at)
            ).scalars().all()
            for r in rows:
                kinds = []
                if r.source_kind not in KNOWN_SOURCE_KINDS:
                    kinds.append("unknown_source_kind")
                if not r.content_hash or len(r.content_hash) != 64:
                    kinds.append("bad_content_hash")
                if not (MIN_TRUST_LEVEL <= r.trust_ladder <= MAX_TRUST_LEVEL):
                    kinds.append("trust_ladder_out_of_bounds")
                if kinds:
                    report_rows.append({
                        "evidence_id": r.evidence_id,
                        "source_kind": r.source_kind,
                        "content_hash": r.content_hash,
                        "trust_ladder": r.trust_ladder,
                        "kinds": kinds,
                    })
        return report_rows

    def research_packages_drift(self) -> List[Dict[str, Any]]:
        """Knowledge-factory rows whose cited evidence no longer exists.

        `ResearchPackageRepository.record` refuses a citation that does not
        exist at record time, so a package citing a row the plane does not know
        can only appear through out-of-band edits. It is still reported and
        takes the report red, because a knowledge entry whose lineage is broken
        silently would make the factory look healthy while it cites ghosts.
        """
        report_rows = []
        with self._db() as session:
            packages = session.execute(
                select(ResearchPackageRecord)
            ).scalars().all()
            if not packages:
                return report_rows
            wanted = {e for p in packages
                      for e in _row_to_package(p).get("evidence_ids", [])}
            found = set(session.execute(
                select(EvidenceRecord.evidence_id).where(
                    EvidenceRecord.evidence_id.in_(wanted))
            ).scalars().all())
        for package in packages:
            missing = [e for e in _row_to_package(package).get("evidence_ids", [])
                       if e not in found]
            if missing:
                report_rows.append({
                    "package_id": package.package_id,
                    "title": package.title,
                    "missing_ids": missing,
                })
        return report_rows

    def research_missions_drift(self) -> List[Dict[str, Any]]:
        """Research missions whose links left the store (RMI-03, row 752).

        `ResearchMissionRepository.create` only issues a mission against a
        queue item the ledger holds, and `deliver` only stamps an
        `output_package_id` the knowledge factory just recorded, so a mission
        pointing at an unknown queue item, a delivered mission without its
        package, or a status outside the known lifecycle can only appear
        through out-of-band edits. Reported red all the same: a mission loop
        that silently lost its links would look healthy while its Paperclip ->
        CrewAI -> Package chain is broken.
        """
        report_rows = []
        with self._db() as session:
            missions = session.execute(
                select(ResearchMissionRecord)
            ).scalars().all()
            if not missions:
                return report_rows
            queue_ids = {m.queue_item_id for m in missions}
            found_queue = set(session.execute(
                select(ResearchQueueItemRecord.item_id).where(
                    ResearchQueueItemRecord.item_id.in_(queue_ids))
            ).scalars().all())
            package_ids = {m.output_package_id for m in missions
                           if m.output_package_id}
            found_packages = set(session.execute(
                select(ResearchPackageRecord.package_id).where(
                    ResearchPackageRecord.package_id.in_(package_ids))
            ).scalars().all()) if package_ids else set()
        for mission in missions:
            problems = []
            if mission.queue_item_id not in found_queue:
                problems.append("unknown_queue_item")
            if mission.status not in MISSION_STATUSES:
                problems.append("unknown_status")
            if (mission.status == "delivered"
                    and mission.output_package_id not in found_packages):
                problems.append("unknown_output_package")
            if problems:
                report_rows.append({
                    "mission_id": mission.mission_id,
                    "queue_item_id": mission.queue_item_id,
                    "status": mission.status,
                    "problems": problems,
                })
        return report_rows

    def report(self) -> Dict[str, Any]:
        """One call for a health or status endpoint."""
        connections = self.orphaned_connections()
        conflicts = self.identity_conflicts()
        unowned = self.unowned_accounts()
        bindings = self.orphaned_bindings()
        referrals = self.orphaned_referrals()
        events = self.orphaned_referral_events()
        evidence = self.evidence_drift()
        packages = self.research_packages_drift()
        missions = self.research_missions_drift()
        return {
            "ok": not (connections or conflicts or unowned or bindings
                       or referrals or events or evidence or packages
                       or missions),
            "orphaned_connections": len(connections),
            "identity_conflicts": len(conflicts),
            "unowned_accounts": len(unowned),
            "orphaned_strategy_bindings": len(bindings),
            "orphaned_referrals": len(referrals),
            "orphaned_referral_events": len(events),
            "evidence_drift": len(evidence),
            "research_packages_drift": len(packages),
            "research_missions_drift": len(missions),
            "details": {
                "connections": connections,
                "conflicts": conflicts,
                "accounts": unowned,
                "strategy_bindings": bindings,
                "referrals": referrals,
                "referral_events": events,
                "evidence": evidence,
                "research_packages": packages,
                "research_missions": missions,
            },
        }



# RMI Factory: the formal source registry and the research queue (row 749,
# RMI-01 of the operator's Research & Market Intelligence Factory build plan).
# Both are durable reference/decision rows, not trade surfaces: no
# grants_trade_permission column anywhere, is_authorisation rides every
# outgoing payload (rows 741/746/748).

SOURCE_TYPES = ("academic", "code", "macro", "market", "news", "sentiment",
                "internal")
RMI_REGISTRY_KINDS = ("arxiv", "ssrn", "github", "macro", "market", "news",
                      "sentiment", "internal")
SOURCE_STATUSES = ("active", "retired")
SOURCE_COSTS = ("free", "tiered", "paid")

# External evidence providers (S9 ecosystem). A partner's `kind` says what sort
# of provider it is; its `status` is a lifecycle (a suspended or retired partner
# cannot receive new evidence attribution).
PARTNER_KINDS = ("academic", "data_vendor", "community", "institution",
                 "individual")
PARTNER_STATUSES = ("active", "suspended", "retired")

# Partner Network (S11). An attestation is the *operator's* onboarding act for an
# external partner integration -- a durable fact distinct from the provider
# registry row (row 743), which records what a provider *is* but no adoption
# step. The lifecycle retires an integration without deleting its provenance.
ATTESTATION_STATUSES = ("attested", "suspended", "retired")

QUEUE_STATUSES = ("queued", "active", "completed", "superseded")
QUEUE_FROM = {
    "active": ("queued",),
    "completed": ("active",),
    "superseded": ("queued", "active"),
}
QUEUE_DIMENSIONS = ("expected_value", "data_availability", "research_cost",
                    "risk", "novelty", "reproducibility")

_SOURCE_ID_RE = None


def _source_id_ok(source_id: str) -> bool:
    import re
    return re.fullmatch(r"[a-z0-9][a-z0-9._-]*", source_id) is not None


def _validate_unit(v, name: str) -> float:
    try:
        value = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number in 0..1") from exc
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be in 0..1, got {value!r}")
    return value


def _resolve_partner(session, partner_id: str) -> str:
    """Resolve an attribution to an active partner, or refuse (fail-closed).

    An empty id means "no partner" (returns ""). A non-empty id must name a
    registered, *active* partner: attributing external evidence to an unknown
    name, or to a suspended/retired provider, is refused rather than silently
    stored.
    """
    value = str(partner_id or "").strip()
    if not value:
        return ""
    row = session.get(EvidencePartnerRecord, value)
    if row is None:
        raise ValueError(
            f"unknown partner {value!r}; register it before attributing evidence")
    if row.status != "active":
        raise ValueError(
            f"partner {value!r} is {row.status}; only an active partner may "
            "receive new evidence")
    return value


def _validate_evidence_ids(session, wanted) -> None:
    stripped = sorted({str(e or "").strip() for e in (wanted or []) if e})
    if not stripped:
        raise ValueError(
            "the cited evidence list is empty; callers that allow un-grounded "
            "rows must skip this check when nothing was cited")
    found = set(session.execute(
        select(EvidenceRecord.evidence_id).where(
            EvidenceRecord.evidence_id.in_(stripped))
    ).scalars().all())
    missing = [e for e in stripped if e not in found]
    if missing:
        raise ValueError(
            "the cited ids do not exist in the plane: "
            f"{', '.join(missing)}")


def _row_to_source(row: SourceRegistryRecord) -> Dict[str, Any]:
    def _loads(raw: str) -> List[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "source_id": row.source_id,
        "source_type": row.source_type,
        "provider": row.provider,
        "partner_id": row.partner_id,
        "kind": row.kind,
        "url_or_feed": row.url_or_feed,
        "frequency": row.frequency,
        "markets": _loads(row.markets_json),
        "topics": _loads(row.topics_json),
        "reliability": row.reliability,
        "cost": row.cost,
        "license": row.license,
        "last_sync": row.last_sync,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_partner(row: EvidencePartnerRecord) -> Dict[str, Any]:
    return {
        "partner_id": row.partner_id,
        "name": row.name,
        "kind": row.kind,
        "status": row.status,
        "contact": row.contact,
        "homepage": row.homepage,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class EvidencePartnerRepository:
    """Durable ledger of external evidence providers (S9 ecosystem).

    A partner is the accountable identity behind a stream of external matter.
    Attribution is fail-closed: an unknown or non-active partner cannot receive
    new evidence, and a slug that is not a canonical lowercase identifier is
    refused. The registry is reference data -- a partner is a knowledge
    provider, never a permission.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def register(self, *, partner_id: str, name: str, kind: str,
                 status: str = "active", contact: str = "",
                 homepage: str = "", note: str = "") -> Dict[str, Any]:
        value = str(partner_id or "").strip()
        if not _source_id_ok(value):
            raise ValueError(
                "partner_id must be a lowercase slug (letters/digits/_/./-)")
        if not str(name or "").strip():
            raise ValueError("a partner needs a name")
        if str(kind or "").strip() not in PARTNER_KINDS:
            raise ValueError(
                "unknown partner kind; known kinds are "
                f"{', '.join(PARTNER_KINDS)}")
        if str(status or "").strip() not in PARTNER_STATUSES:
            raise ValueError(
                "unknown partner status; known statuses are "
                f"{', '.join(PARTNER_STATUSES)}")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            if session.get(EvidencePartnerRecord, value) is not None:
                raise ValueError(f"partner {value!r} is already registered")
            row = EvidencePartnerRecord(
                partner_id=value,
                name=str(name).strip(),
                kind=str(kind).strip(),
                status=str(status).strip(),
                contact=str(contact or "").strip(),
                homepage=str(homepage or "").strip(),
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_partner(row)

    def get(self, partner_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(EvidencePartnerRecord, str(partner_id or ""))
        return _row_to_partner(row) if row is not None else None

    def list_all(self, *, kind: str = "", status: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(EvidencePartnerRecord)
            if kind:
                if kind not in PARTNER_KINDS:
                    raise ValueError("unknown partner kind filter")
                query = query.where(EvidencePartnerRecord.kind == kind)
            if status:
                if status not in PARTNER_STATUSES:
                    raise ValueError("unknown partner status filter")
                query = query.where(EvidencePartnerRecord.status == status)
            rows = session.execute(
                query.order_by(EvidencePartnerRecord.partner_id).limit(limit)
            ).scalars().all()
        return [_row_to_partner(r) for r in rows]

    def set_status(self, partner_id: str, status: str) -> Dict[str, Any]:
        if status not in PARTNER_STATUSES:
            raise ValueError(
                f"unknown partner status {status!r}; known statuses are "
                f"{', '.join(PARTNER_STATUSES)}")
        with self._db() as session:
            row = session.get(EvidencePartnerRecord, str(partner_id or ""))
            if row is None:
                raise ValueError(f"no registered partner {partner_id!r}")
            row.status = status
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_partner(row)

    def summary(self) -> Dict[str, Any]:
        """Partner roster plus real attribution counts (never fabricated)."""
        partners = self.list_all()
        per_kind: Dict[str, int] = {}
        per_status: Dict[str, int] = {}
        for row in partners:
            per_kind[row["kind"]] = per_kind.get(row["kind"], 0) + 1
            per_status[row["status"]] = per_status.get(row["status"], 0) + 1
        with self._db() as session:
            evidence_counts = dict(session.execute(
                select(EvidenceRecord.partner_id, func.count())
                .where(EvidenceRecord.partner_id != "")
                .group_by(EvidenceRecord.partner_id)).all())
            source_counts = dict(session.execute(
                select(SourceRegistryRecord.partner_id, func.count())
                .where(SourceRegistryRecord.partner_id != "")
                .group_by(SourceRegistryRecord.partner_id)).all())
            attributed_evidence = sum(evidence_counts.values())
            total_evidence = session.execute(
                select(func.count()).select_from(EvidenceRecord)).scalar() or 0
        per_partner = {
            row["partner_id"]: {
                "evidence": int(evidence_counts.get(row["partner_id"], 0)),
                "sources": int(source_counts.get(row["partner_id"], 0)),
            } for row in partners
        }
        return {
            "total": len(partners),
            "per_kind": per_kind,
            "per_status": per_status,
            "active": per_status.get("active", 0),
            "attributed_evidence": int(attributed_evidence),
            "unattributed_evidence": int(total_evidence - attributed_evidence),
            "per_partner": per_partner,
        }


class SourceRegistryRepository:
    """Durable, validated ledger of every research source the factory may use.

    A source enters the ledger with a canonical slug `source_id`, one of the
    operator's seven `source_type` categories, the plane family it feeds
    (`kind`), a provider and a cost/license/reliability statement. Unknown
    type/kind/status/cost, a malformed slug, an out-of-range reliability and a
    duplicate source_id are all refused (fail-closed): the registry never
    stores a row nobody can interpret.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def register(self, *, source_id: str, source_type: str, provider: str,
                 kind: str = "", url_or_feed: str = "", frequency: str = "",
                 markets: Optional[List[str]] = None,
                 topics: Optional[List[str]] = None,
                 reliability: float = 0.0, cost: str = "free",
                 license: str = "", status: str = "active",
                 partner_id: str = "", note: str = "") -> Dict[str, Any]:
        value = str(source_id or "").strip()
        if not _source_id_ok(value):
            raise ValueError(
                "source_id must be a lowercase slug (letters/digits/_/./-)")
        if str(source_type or "").strip() not in SOURCE_TYPES:
            raise ValueError(
                "unknown source_type; known types are "
                f"{', '.join(SOURCE_TYPES)}")
        if not str(provider or "").strip():
            raise ValueError("a registered source needs a provider")
        if str(kind or "").strip() not in RMI_REGISTRY_KINDS:
            raise ValueError(
                "unknown source kind; known kinds are "
                f"{', '.join(RMI_REGISTRY_KINDS)}")
        if str(status or "").strip() not in SOURCE_STATUSES:
            raise ValueError(
                "unknown source status; known statuses are "
                f"{', '.join(SOURCE_STATUSES)}")
        if str(cost or "").strip() not in SOURCE_COSTS:
            raise ValueError(
                "unknown cost tier; known tiers are "
                f"{', '.join(SOURCE_COSTS)}")
        rel = _validate_unit(reliability, "reliability")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            if session.get(SourceRegistryRecord, value) is not None:
                raise ValueError(f"source {value!r} is already registered")
            pid = _resolve_partner(session, partner_id)
            row = SourceRegistryRecord(
                source_id=value,
                source_type=str(source_type).strip(),
                provider=str(provider).strip(),
                partner_id=pid,
                kind=str(kind).strip(),
                url_or_feed=str(url_or_feed or "").strip(),
                frequency=str(frequency or "").strip(),
                markets_json=json.dumps(list(dict.fromkeys(
                    str(m).strip() for m in (markets or []) if str(m).strip()))),
                topics_json=json.dumps(list(dict.fromkeys(
                    str(t).strip() for t in (topics or []) if str(t).strip()))),
                reliability=rel,
                cost=str(cost).strip(),
                license=str(license or "").strip(),
                status=str(status).strip(),
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_source(row)

    def get(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(SourceRegistryRecord, str(source_id or ""))
        return _row_to_source(row) if row is not None else None

    def list_all(self, *, source_type: str = "", kind: str = "",
                 status: str = "", partner_id: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(SourceRegistryRecord)
            if source_type:
                if source_type not in SOURCE_TYPES:
                    raise ValueError("unknown source_type filter")
                query = query.where(SourceRegistryRecord.source_type == source_type)
            if kind:
                if kind not in RMI_REGISTRY_KINDS:
                    raise ValueError("unknown kind filter")
                query = query.where(SourceRegistryRecord.kind == kind)
            if status:
                if status not in SOURCE_STATUSES:
                    raise ValueError("unknown status filter")
                query = query.where(SourceRegistryRecord.status == status)
            if partner_id:
                query = query.where(
                    SourceRegistryRecord.partner_id == str(partner_id).strip())
            rows = session.execute(
                query.order_by(SourceRegistryRecord.source_id).limit(limit)
            ).scalars().all()
        return [_row_to_source(r) for r in rows]

    def update(self, source_id: str, *, provider: str = "", kind: str = "",
               url_or_feed: str = "", frequency: str = "",
               markets: Optional[List[str]] = None,
               topics: Optional[List[str]] = None,
               reliability: Optional[float] = None, cost: str = "",
               license: str = "", note: str = "") -> Dict[str, Any]:
        with self._db() as session:
            row = session.get(SourceRegistryRecord, str(source_id or ""))
            if row is None:
                raise ValueError(f"no registered source {source_id!r}")
            if kind and kind not in RMI_REGISTRY_KINDS:
                raise ValueError("unknown kind")
            if cost and cost not in SOURCE_COSTS:
                raise ValueError("unknown cost tier")
            if reliability is not None:
                row.reliability = _validate_unit(reliability, "reliability")
            row.provider = str(provider or row.provider)
            row.kind = str(kind or row.kind)
            row.url_or_feed = str(url_or_feed or row.url_or_feed)
            row.frequency = str(frequency or row.frequency)
            if markets is not None:
                row.markets_json = json.dumps(list(dict.fromkeys(
                    str(m).strip() for m in markets if str(m).strip())))
            if topics is not None:
                row.topics_json = json.dumps(list(dict.fromkeys(
                    str(t).strip() for t in topics if str(t).strip())))
            row.cost = str(cost or row.cost)
            row.license = str(license or row.license)
            if note != "__keep__":
                row.note = str(note or "")
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_source(row)

    def set_status(self, source_id: str, status: str) -> Dict[str, Any]:
        if status not in SOURCE_STATUSES:
            raise ValueError(
                f"unknown source status {status!r}; known statuses are "
                f"{', '.join(SOURCE_STATUSES)}")
        with self._db() as session:
            row = session.get(SourceRegistryRecord, str(source_id or ""))
            if row is None:
                raise ValueError(f"no registered source {source_id!r}")
            row.status = status
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return _row_to_source(row)

    def mark_synced(self, source_id: str) -> Dict[str, Any]:
        with self._db() as session:
            row = session.get(SourceRegistryRecord, str(source_id or ""))
            if row is None:
                raise ValueError(f"no registered source {source_id!r}")
            row.last_sync = datetime.now(timezone.utc).isoformat()
            row.updated_at = row.last_sync
            session.commit()
            return _row_to_source(row)


def _row_to_queue_item(row: ResearchQueueItemRecord) -> Dict[str, Any]:
    def _loads(raw: str) -> List[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "item_id": row.item_id,
        "problem": row.problem,
        "expected_value": row.expected_value,
        "data_availability": row.data_availability,
        "research_cost": row.research_cost,
        "risk": row.risk,
        "novelty": row.novelty,
        "reproducibility": row.reproducibility,
        "priority_score": row.priority_score,
        "priority_label": row.priority_label,
        "evidence_ids": _loads(row.evidence_ids_json),
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


class ResearchQueueRepository:
    """The scored problem ledger the lab works top-down (row 749).

    Enqueue validates every scored dimension into 0..1, requires a problem,
    validates cited evidence when ANY is offered (fail-closed on ghost ids; an
    un-grounded problem is allowed -- the queue holds matters yet to study, and
    grounding is optional, never invented), computes priority_score +
    priority_label via `research.queue.priority.ResearchPriorityScorer`, and
    orders reads by score descending so the lab studies what is worth the cost
    of research first. Transitions follow `QUEUE_FROM`; terminal rows
    (completed / superseded) stay as provenance and are never re-opened.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def enqueue(self, *, problem: str,
                expected_value: float = 0.0,
                data_availability: float = 0.0,
                research_cost: float = 0.0, risk: float = 0.0,
                novelty: float = 0.0, reproducibility: float = 0.0,
                evidence_ids: Optional[List[str]] = None,
                note: str = "") -> Dict[str, Any]:
        value = str(problem or "").strip()
        if not value:
            raise ValueError("a research queue problem needs a problem")
        dims = {}
        for name in QUEUE_DIMENSIONS:
            dims[name] = _validate_unit(locals().get(name), name)
        from research.queue.priority import ResearchPriorityScorer
        scorer = ResearchPriorityScorer()
        score = scorer.score(**dims)
        cited = [str(e or "").strip() for e in (evidence_ids or []) if e]
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            if cited:
                _validate_evidence_ids(session, cited)
            row = ResearchQueueItemRecord(
                item_id=uuid.uuid4().hex,
                problem=value,
                expected_value=dims["expected_value"],
                data_availability=dims["data_availability"],
                research_cost=dims["research_cost"],
                risk=dims["risk"],
                novelty=dims["novelty"],
                reproducibility=dims["reproducibility"],
                priority_score=score,
                priority_label=scorer.label_for(score),
                evidence_ids_json=json.dumps(sorted(set(cited))),
                status="queued",
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_queue_item(row)

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ResearchQueueItemRecord, str(item_id or ""))
        return _row_to_queue_item(row) if row is not None else None

    def list_all(self, *, status: str = "", limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ResearchQueueItemRecord)
            if status:
                if status not in QUEUE_STATUSES:
                    raise ValueError("unknown queue status filter")
                query = query.where(ResearchQueueItemRecord.status == status)
            rows = session.execute(
                query.order_by(ResearchQueueItemRecord.priority_score.desc(),
                               ResearchQueueItemRecord.created_at)
                .limit(limit)
            ).scalars().all()
        return [_row_to_queue_item(r) for r in rows]

    def transition(self, item_id: str, to: str) -> Dict[str, Any]:
        if to not in QUEUE_FROM:
            raise ValueError(
                f"unknown queue status {to!r}; known statuses are "
                f"{', '.join(QUEUE_STATUSES)}")
        with self._db() as session:
            row = session.get(ResearchQueueItemRecord, str(item_id or ""))
            if row is None:
                raise ValueError(f"no queue item {item_id!r}")
            if row.status in ("completed", "superseded"):
                raise ValueError(
                    f"queue item is {row.status}; a terminal item is never "
                    "re-opened")
            if row.status not in QUEUE_FROM[to]:
                raise ValueError(
                    f"illegal queue transition {row.status} -> {to}; allowed "
                    f"into {to}: {', '.join(QUEUE_FROM[to])}")
            now = datetime.now(timezone.utc).isoformat()
            row.status = to
            row.updated_at = now
            if to == "active":
                row.started_at = now
            if to == "completed":
                row.completed_at = now
            session.commit()
            return _row_to_queue_item(row)

    def summary(self) -> Dict[str, Any]:
        rows = self.list_all()
        per_status: Dict[str, int] = {s: 0 for s in QUEUE_STATUSES}
        queued_scores = []
        for row in rows:
            per_status[row["status"]] = per_status.get(row["status"], 0) + 1
            if row["status"] == "queued":
                queued_scores.append(row["priority_score"])
        top = sorted((r for r in rows if r["status"] in ("queued", "active")),
                     key=lambda r: r["priority_score"], reverse=True)[:5]
        return {
            "total": len(rows),
            "per_status": per_status,
            "queued_average_priority": (
                round(sum(queued_scores) / len(queued_scores), 2)
                if queued_scores else 0.0),
            "next_up": [{"item_id": r["item_id"], "problem": r["problem"],
                         "priority_score": r["priority_score"]} for r in top],
            "known_statuses": list(QUEUE_STATUSES),
        }


# RMI-03 (row 752): the Paperclip -> Research Mission -> CrewAI -> Research
# Package loop (MASTER_ARCHITECTURE s8/s9). A mission is a research
# assignment, never a trade surface: no grants_trade_permission column anywhere,
# is_authorisation rides every outgoing payload (rows 741/746/748).

MISSION_STATUSES = ("assigned", "running", "delivered", "failed")
MISSION_FROM = {
    "running": ("assigned",),
    "delivered": ("running",),
    "failed": ("assigned", "running"),
}


def _row_to_mission(row: ResearchMissionRecord) -> Dict[str, Any]:
    def _loads(raw: str) -> List[Any]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "mission_id": row.mission_id,
        "queue_item_id": row.queue_item_id,
        "brief": row.brief,
        "crew": _loads(row.crew_json),
        "model": row.model,
        "status": row.status,
        "output_package_id": row.output_package_id,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


class ResearchMissionRepository:
    """The durable Research Mission ledger of the Paperclip/CrewAI loop.

    Paperclip (the organisation, MASTER_ARCHITECTURE s8) issues a mission
    against an EXISTING queue problem -- the queue decides what may be studied
    (row 749), the mission assigns it to a CrewAI crew. `create` is
    fail-closed: the queue item must exist and not be terminal (a mission is
    never issued against a problem the ledger retired), the brief must say
    something, the crew must be the four canonical s9 roles (an agent cannot
    invent a fifth role or drop the reviewer), and an item with an OPEN mission
    (assigned/running) never gets a second one.

    Lifecycle follows `MISSION_FROM`: `assigned -> running -> delivered`
    (with the `output_package_id` of the package the crew delivered) or
    `assigned|running -> failed` (with the stated reason); delivered/failed are
    terminal and never re-opened. The service -- not this repository -- moves
    the queue item and records the package; this layer only keeps the mission
    row honest.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def create(self, *, queue_item_id: str, brief: str, crew: List[Dict[str,
               Any]], model: str = "", note: str = "") -> Dict[str, Any]:
        from research.missions.crew import CREW_ROLES

        value = str(brief or "").strip()
        if not value:
            raise ValueError("a research mission needs a brief")
        if not isinstance(crew, list) or not crew:
            raise ValueError("a research mission needs a composed crew")
        roles = []
        for seat in crew:
            if not isinstance(seat, dict) or not str(seat.get("role", "")):
                raise ValueError("every crew seat needs a role")
            roles.append(str(seat["role"]))
        if set(roles) != set(CREW_ROLES) or len(roles) != len(set(roles)):
            raise ValueError(
                "the crew must be exactly the canonical roles: "
                f"{', '.join(CREW_ROLES)}")
        wanted_queue_item = str(queue_item_id or "").strip()
        if not wanted_queue_item:
            raise ValueError("a research mission needs a queue item")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            queue_row = session.get(ResearchQueueItemRecord, wanted_queue_item)
            if queue_row is None:
                raise ValueError(
                    f"no queue item {wanted_queue_item!r}; a mission is issued "
                    "against a problem the ledger already holds")
            if queue_row.status in ("completed", "superseded"):
                raise ValueError(
                    f"queue item is {queue_row.status}; a terminal problem is "
                    "never re-opened for a mission")
            open_mission = session.execute(
                select(ResearchMissionRecord).where(
                    ResearchMissionRecord.queue_item_id == wanted_queue_item,
                    ResearchMissionRecord.status.in_(("assigned", "running")))
            ).scalars().first()
            if open_mission is not None:
                raise ValueError(
                    f"queue item {wanted_queue_item!r} already has an open "
                    f"mission {open_mission.mission_id} "
                    f"({open_mission.status})")
            row = ResearchMissionRecord(
                mission_id=uuid.uuid4().hex,
                queue_item_id=wanted_queue_item,
                brief=value,
                crew_json=json.dumps(crew, sort_keys=True),
                model=str(model or "").strip(),
                status="assigned",
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_mission(row)

    def get(self, mission_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ResearchMissionRecord, str(mission_id or ""))
        return _row_to_mission(row) if row is not None else None

    def list_all(self, *, status: str = "", limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ResearchMissionRecord)
            if status:
                if status not in MISSION_STATUSES:
                    raise ValueError("unknown mission status filter")
                query = query.where(ResearchMissionRecord.status == status)
            rows = session.execute(
                query.order_by(ResearchMissionRecord.created_at.desc())
                .limit(limit)
            ).scalars().all()
        return [_row_to_mission(r) for r in rows]

    def _transition(self, mission_id: str, to: str, *,
                    package_id: str = "", note: str = "") -> Dict[str, Any]:
        if to not in MISSION_FROM:
            raise ValueError(
                f"unknown mission status {to!r}; known statuses are "
                f"{', '.join(MISSION_STATUSES)}")
        with self._db() as session:
            row = session.get(ResearchMissionRecord, str(mission_id or ""))
            if row is None:
                raise ValueError(f"no mission {mission_id!r}")
            if row.status in ("delivered", "failed"):
                raise ValueError(
                    f"mission is {row.status}; a terminal mission is never "
                    "re-opened")
            if row.status not in MISSION_FROM[to]:
                raise ValueError(
                    f"illegal mission transition {row.status} -> {to}; "
                    f"allowed into {to}: {', '.join(MISSION_FROM[to])}")
            now = datetime.now(timezone.utc).isoformat()
            row.status = to
            row.updated_at = now
            if to == "running":
                row.started_at = now
            if to == "delivered":
                row.output_package_id = str(package_id or "").strip()
                row.finished_at = now
            if to == "failed":
                if str(note or "").strip():
                    row.note = note.strip()
                row.finished_at = now
            session.commit()
            return _row_to_mission(row)

    def start(self, mission_id: str) -> Dict[str, Any]:
        return self._transition(mission_id, "running")

    def deliver(self, mission_id: str, package_id: str) -> Dict[str, Any]:
        if not str(package_id or "").strip():
            raise ValueError("a delivered mission names its package")
        return self._transition(mission_id, "delivered", package_id=package_id)

    def fail(self, mission_id: str, note: str = "") -> Dict[str, Any]:
        return self._transition(mission_id, "failed", note=note)

    def summary(self) -> Dict[str, Any]:
        rows = self.list_all()
        per_status: Dict[str, int] = {s: 0 for s in MISSION_STATUSES}
        for row in rows:
            per_status[row["status"]] = per_status.get(row["status"], 0) + 1
        return {
            "total": len(rows),
            "per_status": per_status,
            "open": per_status["assigned"] + per_status["running"],
            "known_statuses": list(MISSION_STATUSES),
        }


# The REA investigation lifecycle (research/rea). `requested -> running ->
# completed` records a run that the engine answered; `requested|running ->
# failed` records one that could not start or could not be read. completed/failed
# are terminal and never re-opened -- an investigation is a fact about a run, not
# a mutable draft.
REA_JOB_STATUSES = ("requested", "running", "completed", "failed")
REA_JOB_FROM = {
    "running": ("requested",),
    "completed": ("running",),
    "failed": ("requested", "running"),
}


def _row_to_rea_job(row: ReaJobRecord) -> Dict[str, Any]:
    def _loads(raw: str, fallback: Any) -> Any:
        try:
            value = json.loads(raw or "")
        except (TypeError, ValueError):
            return fallback
        return value

    return {
        "job_id": row.job_id,
        "command": row.command,
        "target": row.target,
        "status": row.status,
        "outcome": row.outcome,
        "requested_by": row.requested_by,
        "evidence_id": row.evidence_id,
        "summary": _loads(row.summary_json, {}),
        "progress": _loads(row.progress_json, []),
        "detail": row.detail,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


class ReaJobRepository:
    """The durable ledger of Reverse Engineering Agent investigations.

    REA is an investigation seat: a caller names a declared REA command and a
    local artifact, and the deployment runs the external `rea-agents` engine over
    it. This repository keeps the run honest:

    * `request` opens a row in `requested` with what was asked (command, target,
      requester) -- so an investigation exists before the engine is touched;
    * `start` moves it to `running`;
    * `finish` closes it with the engine's outcome and a bounded evidence summary
      (the full graph is NOT stored here -- only a digest-sized summary; the
      complete record stays in the Evidence Plane when a run is fed there);
    * `fail` closes it with the stated reason.

    Lifecycle follows `REA_JOB_FROM`; terminal rows are never re-opened. Every
    row is self-contained (no ForeignKeys) and carries no permission: an
    investigation is evidence about an artifact, never authority (rows 741/746).
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def request(self, *, command: str, target: str, requested_by: str = "",
                note: str = "") -> Dict[str, Any]:
        wanted_command = str(command or "").strip()
        if not wanted_command:
            raise ValueError("a REA job needs a command")
        wanted_target = str(target or "").strip()
        if not wanted_target:
            raise ValueError("a REA job needs a target")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = ReaJobRecord(
                job_id=uuid.uuid4().hex,
                command=wanted_command,
                target=wanted_target,
                status="requested",
                requested_by=str(requested_by or "").strip(),
                note=str(note or "").strip(),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _row_to_rea_job(row)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(ReaJobRecord, str(job_id or ""))
        return _row_to_rea_job(row) if row is not None else None

    def list_all(self, *, status: str = "", command: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(ReaJobRecord)
            if status:
                if status not in REA_JOB_STATUSES:
                    raise ValueError("unknown REA job status filter")
                query = query.where(ReaJobRecord.status == status)
            if command:
                query = query.where(ReaJobRecord.command == str(command).strip())
            rows = session.execute(
                query.order_by(ReaJobRecord.created_at.desc()).limit(limit)
            ).scalars().all()
        return [_row_to_rea_job(r) for r in rows]

    def start(self, job_id: str) -> Dict[str, Any]:
        return self._transition(job_id, "running")

    def finish(self, job_id: str, *, outcome: str,
               summary: Optional[Dict[str, Any]] = None,
               progress: Optional[List[Any]] = None,
               evidence_id: str = "", detail: str = "") -> Dict[str, Any]:
        if not str(outcome or "").strip():
            raise ValueError("a finished REA job names its outcome")
        return self._transition(
            job_id, "completed", outcome=str(outcome).strip(),
            summary=summary, progress=progress,
            evidence_id=evidence_id, detail=detail)

    def fail(self, job_id: str, *, outcome: str = "engine_failed",
             detail: str = "", progress: Optional[List[Any]] = None
             ) -> Dict[str, Any]:
        return self._transition(
            job_id, "failed", outcome=str(outcome or "engine_failed").strip(),
            detail=detail, progress=progress)

    def _transition(self, job_id: str, to: str, *, outcome: str = "",
                    summary: Optional[Dict[str, Any]] = None,
                    progress: Optional[List[Any]] = None,
                    evidence_id: str = "", detail: str = "") -> Dict[str, Any]:
        if to not in REA_JOB_FROM:
            raise ValueError(
                f"unknown REA job status {to!r}; known statuses are "
                f"{', '.join(REA_JOB_STATUSES)}")
        with self._db() as session:
            row = session.get(ReaJobRecord, str(job_id or ""))
            if row is None:
                raise ValueError(f"no REA job {job_id!r}")
            if row.status in ("completed", "failed"):
                raise ValueError(
                    f"REA job is {row.status}; a terminal investigation is "
                    "never re-opened")
            if row.status not in REA_JOB_FROM[to]:
                raise ValueError(
                    f"illegal REA job transition {row.status} -> {to}; "
                    f"allowed into {to}: {', '.join(REA_JOB_FROM[to])}")
            now = datetime.now(timezone.utc).isoformat()
            row.status = to
            row.updated_at = now
            if outcome:
                row.outcome = outcome
            if summary is not None:
                row.summary_json = json.dumps(summary, sort_keys=True)
            if progress is not None:
                row.progress_json = json.dumps(progress)
            if detail:
                row.detail = str(detail)
            if evidence_id:
                row.evidence_id = str(evidence_id)
            if to == "running":
                row.started_at = now
            if to in ("completed", "failed"):
                row.finished_at = now
            session.commit()
            return _row_to_rea_job(row)

    def summary(self) -> Dict[str, Any]:
        rows = self.list_all()
        per_status: Dict[str, int] = {s: 0 for s in REA_JOB_STATUSES}
        per_outcome: Dict[str, int] = {}
        for row in rows:
            per_status[row["status"]] = per_status.get(row["status"], 0) + 1
            if row["outcome"]:
                per_outcome[row["outcome"]] = per_outcome.get(
                    row["outcome"], 0) + 1
        return {
            "total": len(rows),
            "per_status": per_status,
            "per_outcome": per_outcome,
            "open": per_status["requested"] + per_status["running"],
            "known_statuses": list(REA_JOB_STATUSES),
        }
