"""Developer API tokens (S10 Developer Platform).

The security bar is the same one the auth milestone set: the system's claims
about its own credential must be TRUE. These tests pin the properties that make
a developer token honest and narrow:

- the plaintext is returned once at mint and never stored -- only a digest is at
  rest, and no read path ever returns the secret or the digest;
- verification accepts a live token and refuses an unknown, malformed, expired
  or revoked one;
- scopes are a bounded ceiling: `read` cannot write, the write scopes can, and a
  token grants nothing beyond its owner;
- mint is fail-closed: a blank owner/label, an empty scope set, an unknown scope
  and a non-positive TTL are all refused;
- revocation and the registry are durable -- a fresh service on the same path
  sees the revoked token as revoked;
- a persistence failure degrades to `durable: False` and never crashes the mint;
- the summary and policy report real values, never fabricated ones.

Enforcement wiring (a token acting as its owner through the request gate) is
covered by the route tests.
"""

from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.api_tokens import (  # noqa: E402
    TOKEN_PREFIX,
    TOKEN_SCOPES,
    ApiTokenError,
    ApiTokenService,
    looks_like_api_token,
)


@pytest.fixture()
def path(tmp_path, monkeypatch):
    target = tmp_path / "api_tokens.json"
    monkeypatch.setenv("TRADERAIG_API_TOKENS_FILE", str(target))
    return target


@pytest.fixture()
def store(path):
    return ApiTokenService()


# -- the secret is returned once and never stored ----------------------------


def test_mint_returns_the_secret_once_and_stores_only_a_digest(store, path):
    minted = store.mint("u1", label="ci", scopes=("read",))
    assert minted["token"].startswith(TOKEN_PREFIX)
    assert minted["token_id"]
    public = store.get(minted["token_id"]).as_dict()
    assert "token" not in public
    assert "hash" not in public
    raw = path.read_text(encoding="utf-8")
    assert minted["token"] not in raw
    assert "hash" in raw


def test_verify_round_trips_a_live_token(store):
    minted = store.mint("u1", label="ci", scopes=("read", "trade"))
    principal = store.verify(minted["token"])
    assert principal.user_id == "u1"
    assert set(principal.scopes) == {"read", "trade"}


def test_verify_refuses_unknown_and_malformed(store):
    for bad in ("", "taigdev_does-not-exist", "v1.a.b", "nonsense"):
        with pytest.raises(ApiTokenError):
            store.verify(bad)


def test_scopes_are_a_ceiling(store):
    read = store.verify(store.mint("u1", label="r", scopes=("read",))["token"])
    write = store.verify(
        store.mint("u1", label="w", scopes=("manage_risk",))["token"])
    assert read.can_write is False
    assert write.can_write is True


# -- mint is fail-closed ------------------------------------------------------


def test_mint_refuses_bad_requests(store):
    with pytest.raises(ApiTokenError):
        store.mint("", label="ci")
    with pytest.raises(ApiTokenError):
        store.mint("u1", label="  ")
    with pytest.raises(ApiTokenError):
        store.mint("u1", label="ci", scopes=())
    with pytest.raises(ApiTokenError):
        store.mint("u1", label="ci", scopes=("read", "root"))
    with pytest.raises(ApiTokenError):
        store.mint("u1", label="ci", ttl_seconds=0)
    with pytest.raises(ApiTokenError):
        store.mint("u1", label="ci", ttl_seconds="soon")


# -- integrity: revoke, expiry, durability -----------------------------------


def test_revoke_then_verify_is_refused(store):
    minted = store.mint("u1", label="ci")
    store.verify(minted["token"])  # live
    store.revoke(minted["token_id"])
    with pytest.raises(ApiTokenError):
        store.verify(minted["token"])


def test_revocation_and_registry_survive_a_restart(path):
    first = ApiTokenService()
    live = first.mint("u1", label="live")
    doomed = first.mint("u1", label="doomed")
    first.revoke(doomed["token_id"])
    # A fresh service on the same file is a restart.
    second = ApiTokenService()
    assert second.verify(live["token"]).token_id == live["token_id"]
    with pytest.raises(ApiTokenError):
        second.verify(doomed["token"])


def test_expired_token_is_refused(store):
    minted = store.mint("u1", label="ci", ttl_seconds=0.02)
    assert store.verify(minted["token"]).is_active() is True
    time.sleep(0.05)
    with pytest.raises(ApiTokenError):
        store.verify(minted["token"])


def test_persist_failure_degrades_to_not_durable(store, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("TRADERAIG_API_TOKENS_FILE",
                       str(blocker / "tokens.json"))
    minted = store.mint("u1", label="ci")  # must not raise
    assert store.durable is False
    assert store.verify(minted["token"]).token_id == minted["token_id"]


# -- reads, summary, policy ---------------------------------------------------


def test_get_list_and_filter(store):
    store.mint("u1", label="a")
    store.mint("u1", label="b")
    store.mint("u2", label="c")
    assert len(store.list_all(user_id="u1")) == 2
    assert len(store.list_all()) == 3
    assert store.get("nope") is None


def test_revoke_unknown_is_refused(store):
    with pytest.raises(ApiTokenError):
        store.revoke("nope")


def test_summary_reports_real_counts(store):
    store.mint("u1", label="a", scopes=("read",))
    store.mint("u1", label="b", scopes=("read", "trade"))
    revoked = store.mint("u1", label="c")
    store.revoke(revoked["token_id"])
    store.mint("u1", label="d", ttl_seconds=0.01)
    time.sleep(0.03)
    summary = store.summary()
    assert summary["total"] == 4
    assert summary["active"] == 2
    assert summary["revoked"] == 1
    assert summary["expired"] == 1
    assert summary["per_scope"]["read"] == 4
    assert summary["per_scope"]["trade"] == 1
    assert summary["is_authorisation"] is False
    assert summary["trade_authority"] == "risk/governor.py"


def test_policy_and_prefix_helper(store):
    policy = store.policy()
    assert policy["prefix"] == TOKEN_PREFIX
    assert policy["scopes"] == list(TOKEN_SCOPES)
    assert policy["hashed_at_rest"] is True
    assert policy["revocable"] is True
    assert looks_like_api_token(TOKEN_PREFIX + "abc") is True
    assert looks_like_api_token("v1.a.b") is False
    assert looks_like_api_token(None) is False
