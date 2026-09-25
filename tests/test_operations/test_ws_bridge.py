"""Real-time MT5 bridge channel tests: WebSocket route, hub fan-out, token
auth, single-authority enforcement, MT5Bridge publish hook, and the
terminal-side proxy file round-trip. Runs over the real FastAPI routing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import operations.api as api
import scripts.mt5_bridge_proxy as proxy
from core.contracts import TradeDirection
from decision.candidate import TradeCandidate
from execution.bridge import MT5Bridge
from operations.ws_bridge import SIGNAL_TOPIC, hub


def _candidate(symbol: str = "XAUUSD", direction=TradeDirection.LONG):
    return TradeCandidate(
        candidate_id=f"cand-{symbol.lower()}",
        thesis_id="th-1",
        symbol=symbol,
        direction=direction,
        entry=2700.0,
        stop_loss=2690.0,
        take_profit=2730.0,
        size=0.01,
        risk_reward=2.0,
        confidence=0.62,
    )


@pytest.fixture(autouse=True)
def _clean_hub():
    hub.clear()
    yield
    hub.clear()


@pytest.fixture()
def client():
    return TestClient(api.app)


def _wait_until(predicate, timeout: float = 3.0):
    """Poll until predicate() holds; the WS receive loop records asynchronously."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def test_hello_handshake(client):
    with client.websocket_connect("/bridge/ws") as ws:
        hello = ws.receive_json()
        assert hello["msg"] == "hello"
        assert hello["session_id"]
        st = api.bridge_status()
        assert st["open"] is True
        assert any(s["id"] == hello["session_id"] for s in st["sessions"])


def test_signal_fanout_two_clients(client):
    frame = {"msg": "signal", "topic": SIGNAL_TOPIC,
             "payload": {"symbol": "XAUUSD", "action": "buy"}}
    with client.websocket_connect("/bridge/ws") as a, \
            client.websocket_connect("/bridge/ws") as b:
        a.receive_json()
        b.receive_json()
        delivered = hub.publish(SIGNAL_TOPIC, frame)
        assert delivered == 2
        assert a.receive_json() == frame
        assert b.receive_json() == frame


def test_client_ack_and_status_are_recorded(client):
    with client.websocket_connect("/bridge/ws") as ws:
        hello = ws.receive_json()
        sid = hello["session_id"]
        ws.send_text(json.dumps(
            {"msg": "ack", "payload": {"candidate_id": "cand-x", "accepted": True}}))
        ws.send_text(json.dumps(
            {"msg": "status", "payload": {"bridge": {"status": "ack"},
                                          "polled_at": 1.0}}))
        st = api.bridge_status()
        me = next(s for s in st["sessions"] if s["id"] == sid)
        _wait_until(lambda: (next(s for s in api.bridge_status()["sessions"]
                                  if s["id"] == sid).get("last_ack") or {})
                    .get("candidate_id") == "cand-x")
        _wait_until(lambda: (next(s for s in api.bridge_status()["sessions"]
                                  if s["id"] == sid).get("last_status") or {})
                    .get("bridge", {}).get("status") == "ack")
        me = next(s for s in api.bridge_status()["sessions"] if s["id"] == sid)
        assert me["last_ack"]["candidate_id"] == "cand-x"
        assert me["last_status"]["bridge"]["status"] == "ack"


def test_token_auth_enforced(client, monkeypatch):
    monkeypatch.setenv("TRADERAIG_BRIDGE_TOKEN", "secret-token")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/bridge/ws?token=wrong") as ws:
            ws.receive_json()
    with client.websocket_connect("/bridge/ws?token=secret-token") as ws:
        hello = ws.receive_json()
        assert hello["msg"] == "hello"


def test_malformed_frame_is_rejected(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text("this is not json")
        err = ws.receive_json()
        assert err["msg"] == "error"
        assert err["error"] == "malformed frame"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_server_rejects_client_signal_single_authority(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"msg": "signal", "payload": {}}))
        err = ws.receive_json()
        assert err["msg"] == "error"
        assert "single signal authority" in err["error"]


def test_mt5bridge_send_signal_publishes_ws_and_writes_file(client, tmp_path):
    bridge = MT5Bridge(filename="bridge_test.json", directory=str(tmp_path))
    candidate = _candidate()
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        assert bridge.send_signal(candidate) is True
        frame = ws.receive_json()
        assert frame["msg"] == "signal"
        assert frame["payload"]["symbol"] == "XAUUSD"
        assert frame["payload"]["candidate_id"] == candidate.candidate_id
        written = json.loads((tmp_path / "bridge_test.json").read_text(
            encoding="utf-8"))
        assert written["signal"] == "trade"


def test_proxy_handle_signal_writes_file_and_acks(tmp_path):
    bridge = MT5Bridge(filename="proxy_test.json", directory=str(tmp_path))
    payload = {"signal": "trade", "symbol": "XAUUSD", "action": "sell",
               "volume": 0.02, "sl": 100, "tp": 200, "price": 2700,
               "candidate_id": "cand-proxy", "sent_at": 1.0}
    marked = [False]
    frames = proxy.handle_server_frame(
        {"msg": "signal", "payload": payload}, bridge, marked)
    ack = frames[0]
    assert ack["msg"] == "ack"
    assert ack["payload"]["accepted"] is True
    assert ack["payload"]["candidate_id"] == "cand-proxy"
    assert marked[0] is True
    written = json.loads((tmp_path / "proxy_test.json").read_text(
        encoding="utf-8"))
    assert written == payload
    status = proxy.build_status(bridge)
    assert status["bridge"]["signal"] == "trade"


def test_proxy_hello_returns_role_and_status(tmp_path):
    bridge = MT5Bridge(filename="proxy_test.json", directory=str(tmp_path))
    marked = [False]
    frames = proxy.handle_server_frame(
        {"msg": "hello", "session_id": "s1"}, bridge, marked)
    assert frames[0] == {"msg": "hello", "role": "terminal"}
    assert frames[1]["msg"] == "status"
