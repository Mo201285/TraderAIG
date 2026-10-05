"""Repositories: persistence implementations of the core contracts.

Each repository maps ORM rows to/from the domain dataclasses without
leaking SQLAlchemy into business logic.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from governance.identity import (
    AuditEntry,
    Entitlement,
    Subscription,
    User,
)
from learning.experience import ErrorType, ExperienceRecord, MarketSnapshot
from persistence.db import bind_test_session, make_live_session
from persistence.models import (
    AuditRecordDB,
    ChallengeBaselineDB,
    ChallengePolicyDB,
    ChallengeProgramBindingDB,
    ChallengeStateDB,
    ExperienceRecordDB,
    OpsRunRecordDB,
    ProductEntitlementDB,
    UserRecord,
    VetoRecordDB,
    dumps,
    loads,
)


class UserRepository:
    """Persists/loads `User` records."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, user: User, subscription: Optional[Subscription] = None) -> None:
        row = self._session.get(UserRecord, user.user_id)
        if row is None:
            row = UserRecord(user_id=user.user_id)
            self._session.add(row)
        row.email = user.email
        row.display_name = user.display_name
        row.plan = user.plan.value
        row.subscription_status = user.subscription_status.value
        row.entitlements_json = dumps(sorted(e.value for e in user.entitlements))
        row.risk_policy_json = dumps(user.risk_policy.as_dict())
        # Deliberately NOT written from `user.account_ids`.
        #
        # That field is the reason this stage needed an account registry: it is a
        # JSON list on `users` that nothing in `operations/`, `risk/`,
        # `execution/` or `challenge/` has ever read, so an account added to it
        # was invisible to every control that would have to act on it. The
        # registry is the readable record now.
        #
        # It is still persisted, as a mirror, so an older build reading this row
        # does not find an empty list. It is a compatibility copy, not a source of
        # truth, and nothing may read it back.
        row.account_ids_json = dumps(
            self._registered_account_ids(user.user_id))
        row.password_hash = user.password_hash
        if user.password_set_at is not None:
            row.password_set_at = user.password_set_at
        if subscription is not None:
            row.expires_at = subscription.expires_at
        row.updated_at = datetime.now(timezone.utc).isoformat()
        self._session.commit()

    def get(self, user_id: str) -> Optional[User]:
        row = self._session.get(UserRecord, user_id)
        if row is None:
            return None
        return self._row_to_user(row)

    def delete(self, user_id: str) -> bool:
        """Remove the user row. Returns True if a row was actually removed.

        Added because this method was missing, not because deletes are new: a
        delete that only touched memory left the row in SQLite, so the user was
        rehydrated on the next boot and the operator had no reason to doubt
        that the deletion had worked.
        """
        row = self._session.get(UserRecord, user_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    def _registered_account_ids(self, user_id: str) -> List[str]:
        """Account ids owned by `user_id`, for the legacy `account_ids_json` mirror.

        Swallows its own errors on purpose. This runs inside `save()` on the user
        hot path, and the mirrored column is a compatibility copy that no code in
        this build reads. A store that cannot be reached should degrade this
        mirror to an empty list and leave the user row correct; raising would turn
        a cosmetic write into a failed login.
        """
        try:
            from persistence.repositories_accounts import AccountRegistryRepository

            rows = AccountRegistryRepository(self._session).list_for_owner(user_id)
            return [r["account_id"] for r in rows]
        except Exception:
            return []

    def refresh_account_mirror(self, user_id: str) -> Optional[List[str]]:
        """Rewrite `account_ids_json` for one user from the registry, now.

        The mirror is otherwise only refreshed as a side effect of `save()`, which
        means any writer that touches the registry without touching the user row
        leaves the mirror stale. That is exactly what adopting an account does, and
        a stale mirror is worse than a missing one: the column exists so that an
        older build reading the row finds the accounts rather than an empty list,
        and an empty list there reads as "this user owns nothing".

        Returns the ids written, or None when there is no such user row -- an owner
        that is not in `users` is a registry inconsistency, and inventing a user
        here would hide it behind a plausible-looking mirror.
        """
        user_id = str(user_id or "").strip()
        if not user_id:
            return None
        row = self._session.get(UserRecord, user_id)
        if row is None:
            return None
        ids = self._registered_account_ids(user_id)
        row.account_ids_json = dumps(ids)
        self._session.commit()
        return ids

    def get_by_email(self, email: str) -> Optional[User]:
        row = self._session.execute(
            select(UserRecord).where(UserRecord.email == email)
        ).scalar_one_or_none()
        return self._row_to_user(row) if row else None

    def list(self, limit: int = 100) -> List[User]:
        rows = self._session.execute(
            select(UserRecord).limit(limit)
        ).scalars().all()
        return [self._row_to_user(r) for r in rows]

    def save_subscription(self, subscription: Subscription) -> None:
        row = self._session.get(UserRecord, subscription.user_id)
        if row is None:
            return
        row.plan = subscription.plan.value
        row.subscription_status = subscription.status.value
        row.expires_at = subscription.expires_at
        row.updated_at = datetime.now(timezone.utc).isoformat()
        self._session.commit()

    @staticmethod
    def _row_to_user(row: UserRecord) -> User:
        from governance.identity import RiskPolicy

        plan = _enum_cast(row.plan, "governance.identity.SubscriptionPlan")
        status = _enum_cast(
            row.subscription_status, "governance.identity.SubscriptionStatus"
        )
        entitlements_raw = loads(row.entitlements_json) or []
        entitlements = {Entitlement(value) for value in entitlements_raw}

        return User(
            user_id=row.user_id,
            email=row.email,
            display_name=row.display_name,
            plan=plan,
            subscription_status=status,
            entitlements=entitlements,
            risk_policy=RiskPolicy(**loads(row.risk_policy_json)),
            account_ids=loads(row.account_ids_json),
            # A database written before authentication existed has no digest;
            # `getattr` rather than `row.` because the attribute only exists once
            # the column is there, and a user with no credential must rehydrate
            # as a user who cannot log in, not as a crash on boot.
            password_hash=getattr(row, "password_hash", None),
            password_set_at=getattr(row, "password_set_at", None),
        )


class ExperienceRepository:
    """Persists/loads `ExperienceRecord` rows."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, record: ExperienceRecord) -> None:
        row = ExperienceRecordDB(
            record_id=record.record_id,
            decision_id=record.decision_id,
            timestamp=record.timestamp,
            thesis_id=record.thesis_id,
            candidate_id=record.candidate_id,
            market_snapshot_json=dumps(record.market_snapshot.__dict__
                                       if record.market_snapshot else {}),
            risk_decision_json=dumps(record.risk_decision or {}),
            actual_result_json=dumps(record.actual_result or {}),
            metadata_json=dumps(record.metadata or {}),
            error_classification=record.error_classification.value
            if record.error_classification else None,
            slippage=record.slippage,
            fees=record.fees,
            lessons_json=dumps(record.lessons),
        )
        self._session.merge(row)
        self._session.commit()

    def list(self, limit: int = 100) -> List[ExperienceRecord]:
        rows = self._session.execute(
            select(ExperienceRecordDB).order_by(
                ExperienceRecordDB.timestamp.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: ExperienceRecordDB) -> ExperienceRecord:
        market_snapshot_raw = loads(row.market_snapshot_json)
        market_snapshot = MarketSnapshot(**market_snapshot_raw) if market_snapshot_raw else None
        error_classification = ErrorType(row.error_classification) if row.error_classification else None
        return ExperienceRecord(
            record_id=row.record_id,
            decision_id=row.decision_id,
            timestamp=row.timestamp,
            thesis_id=row.thesis_id,
            candidate_id=row.candidate_id,
            market_snapshot=market_snapshot,
            risk_decision=loads(row.risk_decision_json),
            actual_result=loads(row.actual_result_json),
            metadata=loads(row.metadata_json),
            error_classification=error_classification,
            slippage=row.slippage,
            fees=row.fees,
            lessons=loads(row.lessons_json),
        )


class RiskVetoRepository:
    """Persists/loads risk-governor veto records (idempotent by decision_id)."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, veto: Dict) -> None:
        row = VetoRecordDB(
            decision_id=str(veto.get("decision_id") or ""),
            candidate_id=str(veto.get("candidate_id") or ""),
            kind=str(veto.get("kind") or "vetoed"),
            reason=str(veto.get("reason") or ""),
            checks_json=dumps(veto.get("checks") or []),
            recorded_at=float(veto.get("recorded_at") or 0.0) or None,
        )
        self._session.merge(row)
        self._session.commit()

    def list(self, limit: int = 300) -> List[Dict]:
        rows = self._session.execute(
            select(VetoRecordDB).order_by(
                VetoRecordDB.recorded_at.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_veto(r) for r in reversed(rows)]

    @staticmethod
    def _row_to_veto(row: VetoRecordDB) -> Dict:
        return {
            "decision_id": row.decision_id,
            "candidate_id": row.candidate_id,
            "kind": row.kind,
            "reason": row.reason,
            "checks": loads(row.checks_json),
            "recorded_at": row.recorded_at,
        }


class ChallengeRepository:
    """Persists challenge baselines and states so a restart forgets nothing.

    Every method here is written to be *safe* when the database is not: a read
    that cannot reach the store returns nothing rather than raising, and a write
    that fails is swallowed by the caller. The reason is asymmetry. Losing a
    baseline write downgrades an account to untrusted, which costs the operator
    a re-declaration. Raising out of the observation path would take the API
    down, and on a 24/7 host that turns a storage problem into an outage. The
    in-memory copy is always the authority for the current process; the row is
    the copy that has to survive it.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        # `make_live_session()`, NOT `bind_test_session()`.
        #
        # Every other repository in this file defaults to an in-memory SQLite
        # with a StaticPool, which is the right trade for a cache you are happy
        # to lose. It is the wrong trade for the one repository whose entire
        # reason to exist is to survive a restart: an in-memory database dies
        # with the process, so the running backend would have answered
        # `durable: true` on every `/challenge/status` while keeping every
        # baseline in RAM. The control would report itself armed with no memory.
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        """A session for one call, closed afterwards.

        Holding a session for the lifetime of the repository pins a connection
        out of the pool for the lifetime of the process, and the pool is five
        plus ten. That is not a theoretical ceiling: a service constructed per
        account, or per test, exhausts it, and every later call then blocks for
        30 seconds and raises. The failure was quiet in the worst possible way
        -- `challenge.service` degrades a store error rather than raising, so
        pool exhaustion surfaced as a log full of warnings and a `durability:
        false` nobody was watching, while the suite stayed green. A degraded
        control that nobody notices is precisely what this repository exists to
        prevent, so the leak is closed here rather than tolerated.

        An injected session belongs to the caller, so it is used as-is and not
        closed; that is the path the tests take when they hand in their own
        engine, and closing it out from under them would break the next call.
        """
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    # -- baselines ------------------------------------------------------

    def save_baseline(self, baseline: Dict[str, Any]) -> None:
        with self._db() as session:
            row = ChallengeBaselineDB(
                account_id=str(baseline.get("account_id") or ""),
                start_equity=_opt_float(baseline.get("start_equity")),
                equity_low=_opt_float(baseline.get("equity_low")),
                equity_peak=_opt_float(baseline.get("equity_peak")),
                day_start_equity=_opt_float(baseline.get("day_start_equity")),
                day_low_equity=_opt_float(baseline.get("day_low_equity")),
                day_epoch=_opt_int(baseline.get("day_epoch")),
                trading_days=int(baseline.get("trading_days") or 0),
                origin=str(baseline.get("origin") or "observed"),
                source=(str(baseline["source"]) if baseline.get("source") else None),
                seeded_at=_opt_float(baseline.get("seeded_at")),
            )
            session.merge(row)
            session.commit()

    def load_baselines(self) -> List[Dict]:
        with self._db() as session:
            rows = session.execute(
                select(ChallengeBaselineDB)).scalars().all()
        return [{
            "account_id": r.account_id,
            "start_equity": r.start_equity,
            "equity_low": r.equity_low,
            "equity_peak": r.equity_peak,
            "day_start_equity": r.day_start_equity,
            "day_low_equity": r.day_low_equity,
            "day_epoch": r.day_epoch,
            "trading_days": int(r.trading_days or 0),
            "origin": r.origin or "observed",
            "source": r.source,
            "seeded_at": r.seeded_at,
        } for r in rows]

    def delete_baseline(self, account_id: str) -> bool:
        with self._db() as session:
            row = session.get(ChallengeBaselineDB, account_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- states ---------------------------------------------------------

    def save_state(self, account_id: str, state: str) -> None:
        with self._db() as session:
            session.merge(ChallengeStateDB(account_id=account_id, state=state))
            session.commit()

    def load_states(self) -> List[Dict]:
        with self._db() as session:
            rows = session.execute(
                select(ChallengeStateDB)).scalars().all()
        return [{"account_id": r.account_id, "state": r.state or "onboarding"}
                for r in rows]

    # -- policies --------------------------------------------------------

    def save_policy(self, policy: Dict[str, Any]) -> None:
        """Persist one policy version.

        The row is keyed by content, not by the registry's composite `key`:
        `key` folds in account size and server scope, so registering the same
        version for two account sizes produces two rows with one version label.
        That is correct -- they are two different policies -- and it means
        `payload` is part of the uniqueness constraint rather than an
        afterthought.
        """
        payload = json.dumps(policy, sort_keys=True, default=str)
        with self._db() as session:
            existing = session.execute(
                select(ChallengePolicyDB).where(
                    ChallengePolicyDB.provider
                    == str(policy.get("provider") or ""),
                    ChallengePolicyDB.program
                    == str(policy.get("program") or ""),
                    ChallengePolicyDB.policy_version
                    == str(policy.get("policy_version") or ""),
                    ChallengePolicyDB.payload == payload,
                )).scalars().first()
            if existing is not None:
                return
            session.add(ChallengePolicyDB(
                provider=str(policy.get("provider") or ""),
                program=str(policy.get("program") or ""),
                policy_version=str(policy.get("policy_version") or ""),
                payload=payload))
            session.commit()

    def load_policies(self) -> List[Dict]:
        with self._db() as session:
            rows = session.execute(
                select(ChallengePolicyDB).order_by(
                    ChallengePolicyDB.registered_at)).scalars().all()
        out: List[Dict] = []
        for r in rows:
            try:
                decoded = json.loads(r.payload)
            except (TypeError, ValueError):
                # A row that will not parse is skipped and named by the caller,
                # never loaded optimistically: half a policy produces confident
                # wrong numbers, which is the failure this whole path exists to
                # prevent.
                out.append({"provider": r.provider, "program": r.program,
                            "policy_version": r.policy_version,
                            "_unreadable": True})
                continue
            decoded["provider"] = r.provider
            decoded["program"] = r.program
            decoded["policy_version"] = r.policy_version
            out.append(decoded)
        return out

    def save_program_binding(self, binding: Dict[str, Any]) -> None:
        """Record which program one MT5 account belongs to.

        Upsert by (login, server) rather than append: re-binding an account to a
        corrected program is the operator fixing their own record, and a table
        that only grows would leave two answers for one account with nothing
        saying which one is in force.
        """
        login = str(binding.get("account_login") or "").strip()
        if not login:
            raise ValueError("a program binding needs the MT5 login it describes")
        with self._db() as session:
            row = session.execute(
                select(ChallengeProgramBindingDB).where(
                    ChallengeProgramBindingDB.account_login == login,
                    ChallengeProgramBindingDB.server
                    == str(binding.get("server") or ""),
                )).scalars().first()
            if row is None:
                session.add(ChallengeProgramBindingDB(
                    account_login=login,
                    server=str(binding.get("server") or ""),
                    provider=str(binding.get("provider") or ""),
                    program=str(binding.get("program") or ""),
                    source=str(binding.get("source") or "")))
            else:
                row.provider = str(binding.get("provider") or "")
                row.program = str(binding.get("program") or "")
                row.source = str(binding.get("source") or "")
                row.bound_at = datetime.now(timezone.utc).timestamp()
            session.commit()

    def load_program_bindings(self) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(ChallengeProgramBindingDB).order_by(
                    ChallengeProgramBindingDB.bound_at)).scalars().all()
        return [{"account_login": r.account_login, "server": r.server,
                 "provider": r.provider, "program": r.program,
                 "source": r.source, "bound_at": r.bound_at}
                for r in rows]

    def delete_program_binding(self, account_login: str,
                              server: str = "") -> bool:
        """Forget a binding. Used by the route that unbinds an account."""
        with self._db() as session:
            row = session.execute(
                select(ChallengeProgramBindingDB).where(
                    ChallengeProgramBindingDB.account_login
                    == str(account_login),
                    ChallengeProgramBindingDB.server == str(server or ""),
                )).scalars().first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


class ProductRepository:
    """Persists paid-product entitlements (§34.2).

    `make_live_session()`, not the in-memory default, for the same reason
    `ChallengeRepository` uses it: an in-memory store would let the running
    backend report `challenge_management: true` for a customer who paid, and then
    lose the receipt at restart. The row is the part that has to survive.

    One row per (user, product) rather than one row per purchase, because the
    question this table answers is "what does this user hold right now", not
    "what has this user ever bought". Renewals are recorded by the audit trail;
    keeping both here would mean two answers to the same question.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or make_live_session()

    def save(self, ent: Any) -> None:
        row = ProductEntitlementDB(
            entitlement_id=str(ent.entitlement_id),
            user_id=str(ent.user_id),
            product_id=str(ent.product_id),
            entitlement=str(ent.entitlement),
            state=str(ent.state),
            price_usd=float(ent.price_usd or 0.0),
            currency=str(ent.currency or "USD"),
            charge_id=str(ent.charge_id or ""),
            started_at=float(ent.started_at or 0.0),
            expires_at=float(ent.expires_at or 0.0),
            grace_until=float(ent.grace_until or 0.0),
            note=str(ent.note or ""),
        )
        self._session.merge(row)
        self._session.commit()

    def load_all(self) -> List[Dict[str, Any]]:
        rows = self._session.execute(
            select(ProductEntitlementDB)).scalars().all()
        return [{
            "entitlement_id": r.entitlement_id,
            "user_id": r.user_id,
            "product_id": r.product_id,
            "entitlement": r.entitlement,
            "state": r.state or "active",
            "price_usd": float(r.price_usd or 0.0),
            "currency": r.currency or "USD",
            "charge_id": r.charge_id or "",
            "started_at": float(r.started_at or 0.0),
            "expires_at": float(r.expires_at or 0.0),
            "grace_until": float(r.grace_until or 0.0),
            "note": r.note or "",
        } for r in rows]

    def delete_for_user(self, user_id: str) -> int:
        rows = self._session.execute(
            select(ProductEntitlementDB).where(
                ProductEntitlementDB.user_id == str(user_id))).scalars().all()
        for row in rows:
            self._session.delete(row)
        self._session.commit()
        return len(rows)


def _opt_float(value: Any) -> Optional[float]:
    """None stays None; 0.0 is a real measurement and must not vanish.

    A baseline of zero is not a baseline (row 735's zero-equity guard), but the
    *stored* value of a legitimately-zero field still has to round-trip, and a
    truthiness filter here would quietly turn 0.0 into NULL.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OpsRunRepository:
    """Persists/loads the summary of the last exercise run (singleton id=1)."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save_last(self, last_run: Optional[str] = None,
                  duration_s: float = 0.0, error: Optional[str] = None) -> None:
        self._session.merge(OpsRunRecordDB(
            id=1, last_run=last_run, duration_s=duration_s, error=error))
        self._session.commit()

    def get_last(self) -> Optional[Dict]:
        row = self._session.execute(
            select(OpsRunRecordDB).where(OpsRunRecordDB.id == 1)
        ).scalars().first()
        if row is None:
            return None
        return {"last_run": row.last_run, "duration_s": row.duration_s,
                "error": row.error}


class AuditRepository:
    """Append-only audit persistence."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def append(self, entry: AuditEntry) -> None:
        row = AuditRecordDB(
            entry_id=entry.entry_id,
            timestamp=entry.timestamp,
            actor=entry.actor,
            action=entry.action,
            object_type=entry.object_type,
            object_id=entry.object_id,
            # An empty string is stored as NULL so "this action concerned no
            # account" stays distinguishable in SQL from a lookup that filtered
            # on the column and found nothing.
            account_id=entry.account_id or None,
            details_json=dumps(entry.details),
            success=entry.success,
        )
        self._session.add(row)
        self._session.commit()

    def list(self, limit: int = 100) -> List[AuditEntry]:
        rows = self._session.execute(
            select(AuditRecordDB).order_by(
                AuditRecordDB.timestamp.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row: AuditRecordDB) -> AuditEntry:
        return AuditEntry(
            entry_id=row.entry_id,
            timestamp=row.timestamp,
            actor=row.actor,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            details=loads(row.details_json),
            success=row.success,
            account_id=row.account_id or "",
        )


def _enum_cast(value: str, enum_dotted: str) -> object:
    """Cast string back to the enum member defined in the given module path."""
    import importlib

    mod_name, _, attr = enum_dotted.rpartition(".")
    module = importlib.import_module(mod_name)
    enum_cls = getattr(module, attr)
    return enum_cls(value)
