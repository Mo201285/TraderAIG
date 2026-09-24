"""Audit behavior tests for governance persistence fallback."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import governance.identity as identity_mod  # noqa: E402
from governance.identity import IdentityService, SubscriptionPlan  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402


def test_audit_log_reads_from_persistence_when_available(monkeypatch):
    session = bind_test_session()

    def _persist(user, subscription=None):
        from persistence.repositories import UserRepository
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)

    import persistence.db as db_mod
    monkeypatch.setattr(db_mod, "make_live_session", lambda: session)
    monkeypatch.setattr(db_mod, "persistence_enabled", lambda: True)

    service = IdentityService()
    user = service.create_user("audit@example.com", "Audit User", SubscriptionPlan.FREE)
    service.activate_subscription(user.user_id, SubscriptionPlan.PRO, duration_seconds=3600)

    logs = service.audit_log(limit=10)
    actions = [entry.action for entry in logs]

    assert "user.create" in actions
    assert "subscription.activate" in actions
