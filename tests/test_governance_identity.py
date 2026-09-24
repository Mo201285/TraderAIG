"""Direct tests for IdentityService subscription and entitlement behavior."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import governance.identity as identity_mod  # noqa: E402
from governance.identity import (  # noqa: E402
    Entitlement,
    IdentityService,
    SubscriptionPlan,
    SubscriptionStatus,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models import UserRecord  # noqa: E402


def test_governance_drawdown_default_and_sync(monkeypatch):
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy

    default_policy = identity_mod.drawdown_policy()
    assert default_policy.mode is DrawdownMode.GOVERNED

    identity_mod.set_governance_drawdown(DrawdownPolicy(
        mode=DrawdownMode.GOV_APPROVE, lab_cap_r=2.0,
        gov_cap_r=15.0, gov_override=True))
    synced = identity_mod.drawdown_policy()
    assert synced.mode is DrawdownMode.GOV_APPROVE
    assert synced.lab_cap_r == 2.0
    assert synced.gov_cap_r == 15.0
    assert synced.gov_override is True

    identity_mod.set_governance_drawdown(DrawdownPolicy())  # restore default


def test_identity_records_audit_entries():
    svc = IdentityService()
    svc.record_audit("lab", "lab.policy_change", "drawdown_policy",
                     "governed", details={"mode": "governed"})
    trail = svc.audit_log(10)
    assert len(trail) == 1
    assert trail[0].action == "lab.policy_change"
    assert trail[0].object_type == "drawdown_policy"


def test_create_user_starts_pending_and_persists_user_mirror(monkeypatch):
    service = IdentityService()
    session = bind_test_session()

    def _persist(user, subscription=None):
        from persistence.repositories import UserRepository
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)

    user = service.create_user("pending@example.com", "Pending User", SubscriptionPlan.FREE)
    row = session.get(UserRecord, user.user_id)

    assert user.subscription_status == SubscriptionStatus.PENDING
    assert service.can(user.user_id, Entitlement.READ_ONLY) is False
    assert row is not None
    assert row.subscription_status == SubscriptionStatus.PENDING.value


def test_activate_subscription_updates_entitlements_and_expiry(monkeypatch):
    service = IdentityService()
    session = bind_test_session()

    def _persist(user, subscription=None):
        from persistence.repositories import UserRepository
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)

    user = service.create_user("pro@example.com", "Pro User", SubscriptionPlan.FREE)
    sub = service.activate_subscription(user.user_id, SubscriptionPlan.PRO, duration_seconds=3600)
    row = session.get(UserRecord, user.user_id)

    assert sub.status == SubscriptionStatus.ACTIVE
    assert service.can(user.user_id, Entitlement.CAN_TRADE) is True
    assert service.can(user.user_id, Entitlement.MULTI_ACCOUNT) is True
    assert row.plan == SubscriptionPlan.PRO.value
    assert row.subscription_status == SubscriptionStatus.ACTIVE.value
    assert row.expires_at == sub.expires_at


def test_expire_subscription_revokes_entitlements_and_updates_db(monkeypatch):
    service = IdentityService()
    session = bind_test_session()

    def _persist(user, subscription=None):
        from persistence.repositories import UserRepository
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)

    user = service.create_user("expire@example.com", "Expire User", SubscriptionPlan.STARTER)
    service.activate_subscription(user.user_id, SubscriptionPlan.STARTER, duration_seconds=3600)
    assert service.can(user.user_id, Entitlement.CAN_TRADE) is True

    service.expire_subscription(user.user_id)
    row = session.get(UserRecord, user.user_id)

    assert service.can(user.user_id, Entitlement.CAN_TRADE) is False
    assert row.subscription_status == SubscriptionStatus.EXPIRED.value
    assert row.entitlements_json == "[]"


def test_rehydrate_restores_users_subscriptions_and_entitlements(monkeypatch):
    session = bind_test_session()

    def _persist(user, subscription=None):
        from persistence.repositories import UserRepository
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)

    writer = IdentityService()
    user = writer.create_user("rehydrate@example.com", "Rehydrate User", SubscriptionPlan.FREE)
    sub = writer.activate_subscription(user.user_id, SubscriptionPlan.PRO, duration_seconds=7200)

    import persistence.db as db_mod
    monkeypatch.setattr(db_mod, "make_live_session", lambda: session)
    monkeypatch.setattr(db_mod, "persistence_enabled", lambda: True)

    restored = IdentityService()
    count = restored.rehydrate()

    loaded = restored.get_user(user.user_id)
    assert count >= 1
    assert loaded is not None
    assert loaded.plan == SubscriptionPlan.PRO
    assert loaded.subscription_status == SubscriptionStatus.ACTIVE
    assert restored.can(user.user_id, Entitlement.CAN_TRADE) is True
    assert restored._subscriptions[user.user_id].expires_at == sub.expires_at
