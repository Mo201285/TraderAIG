"""Real-time MT5 bridge channel tests: WebSocket route, hub fan-out, token
auth, single-authority enforcement, MT5Bridge publish hook, and the
terminal-side proxy file round-trip. Runs over the real FastAPI routing.

Also covers the 28.6 market channel end to end: a terminal `market` frame
over WebSocket and the file bridge both land in the canonical `MarketPlane`
as their own source tier, are rejected (never defaulted) when values are
junk or a symbol is missing, are rate limited, need the bridge token, and can
never displace an MT5-owned quote or bar window.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import operations.api as api
import scripts.mt5_bridge_proxy as proxy
from core.contracts import Candle, TradeDirection
from core.market_plane import MarketPlane, market_plane
from core.state import MarketState, state
from decision.candidate import TradeCandidate
from execution.bridge import MT5Bridge
from operations.ws_bridge import SIGNAL_TOPIC, hub


def _bar(close: float, timeframe: str = "M15",
         symbol: str = "XAUUSD") -> Candle:
    now = time.time()
    return Candle(symbol=symbol, timeframe=timeframe, time=now - 60.0,
                  open=close - 1, high=close + 1, low=close - 2, close=close,
                  volume=1.0, tick_volume=10.0)


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


# -- market channel (28.6): terminal -> canonical plane --------------------

def _market_frame(symbol: str = "XAUUSD", timeframe: str = "M15",
                  close: float = 2400.0) -> dict:
    """A real terminal frame: a forming bar + a real two-sided quote."""
    now = time.time()
    return {
        "msg": "market",
        "payload": {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": [{"time": now - 60.0, "open": close - 2, "high": close + 1,
                      "low": close - 3, "close": close, "tick_volume": 42}],
            "quote": {"bid": close - 0.5, "ask": close + 0.5,
                      "last": close, "tick_time": now},
        },
    }


def test_client_market_frame_lands_in_the_canonical_plane(client):
    with client.websocket_connect("/bridge/ws") as ws:
        hello = ws.receive_json()
        sid = hello["session_id"]
        ws.send_text(json.dumps(_market_frame()))
        ack = ws.receive_json()
        assert ack["msg"] == "market_ack"
        read = market_plane.read("XAUUSD", "M15", allow_pull=False)
        assert read.quote is not None and read.quote.bid == 2399.5
        assert read.candles and read.candles[-1].close == 2400.0
        # a bridge frame is its own provenance tier, never presented as mt5
        assert read.quote_source == f"bridge:{sid}"
        assert read.source == f"bridge:{sid}"
        me = next(s for s in api.bridge_status()["sessions"] if s["id"] == sid)
        assert me["market_frames"] == 1
    state.market.pop("XAUUSD", None)


def test_market_frame_without_a_symbol_is_rejected_not_defaulted(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"msg": "market", "payload": {
            "quote": {"bid": 1.0, "ask": 1.1, "last": 1.05, "tick_time": 1.0}}}))
        err = ws.receive_json()
        assert err["msg"] == "error"
        assert "symbol" in err["error"]
        assert market_plane.quote("XAUUSD") is None


def test_market_frame_keeps_the_real_quote_and_refuses_the_junk_bars(client):
    """Partial acceptance, reported: a real quote is kept, junk bars are not.

    The frame is not thrown away wholesale (its quote is real) and it is not
    accepted wholesale (its bar close was null). The reply says which.
    """
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        frame = _market_frame()
        frame["payload"]["bars"][0]["close"] = None
        ws.send_text(json.dumps(frame))
        ack = ws.receive_json()
        assert ack["msg"] == "market_ack"
        assert ack["market"]["bars"] == 0
        read = market_plane.read("XAUUSD", "M15", allow_pull=False)
        assert read.quote is not None and read.quote.bid == 2399.5
        assert read.candles == []
    state.market.pop("XAUUSD", None)


def test_market_frame_with_only_junk_is_rejected_outright(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        frame = _market_frame()
        frame["payload"]["bars"][0]["close"] = None
        frame["payload"].pop("quote")
        ws.send_text(json.dumps(frame))
        err = ws.receive_json()
        assert err["msg"] == "error" and "unusable bars" in err["error"]
        assert market_plane.read("XAUUSD", "M15",
                                 allow_pull=False).candles == []
    state.market.pop("XAUUSD", None)


def test_one_sided_quote_is_refused_so_no_ask_is_invented(client):
    """A bid without an ask has no honest spread, so it is not a quote."""
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"msg": "market", "payload": {
            "symbol": "XAUUSD", "timeframe": "M15",
            "quote": {"bid": 2400.0, "tick_time": time.time()}}}))
        err = ws.receive_json()
        assert err["msg"] == "error" and "bid and ask" in err["error"]
        assert market_plane.quote("XAUUSD") is None


def test_quote_without_a_real_tick_time_is_refused(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"msg": "market", "payload": {
            "symbol": "XAUUSD", "timeframe": "M15",
            "quote": {"bid": 2400.0, "ask": 2401.0}}}))
        err = ws.receive_json()
        assert err["msg"] == "error" and "tick time" in err["error"]
        assert market_plane.quote("XAUUSD") is None


def test_unknown_timeframe_is_refused_not_defaulted_into_a_window(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        frame = _market_frame(timeframe="FIVE_MIN")
        ws.send_text(json.dumps(frame))
        err = ws.receive_json()
        assert err["msg"] == "error" and "timeframe" in err["error"]
        assert market_plane.window("XAUUSD", "FIVE_MIN") is None
    state.market.pop("XAUUSD", None)


def test_market_frame_needs_an_object_payload(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"msg": "market"}))
        err = ws.receive_json()
        assert err["msg"] == "error" and "payload" in err["error"]


def test_market_frame_cannot_overwrite_an_mt5_owner(client):
    """The gate that matters: a bridge price must never displace MT5's."""
    mt5 = MarketState(symbol="XAUUSD", bid=2700.0, ask=2701.0,
                      last_price=2700.5, last_tick_time=time.time())
    market_plane.publish_quote(mt5, source="mt5")
    market_plane.publish_candles("XAUUSD", "M15", [_bar(2700.5)], source="mt5")
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps(_market_frame(close=2400.0)))
        ack = ws.receive_json()
        assert ack["msg"] == "market_ack"
    read = market_plane.read("XAUUSD", "M15", allow_pull=False)
    assert read.quote is mt5 and read.quote.bid == 2700.0
    assert read.candles[-1].close == 2700.5
    assert read.source == "mt5" and read.single_source is True
    assert market_plane.quote_shadow("XAUUSD")[-1]["source"].startswith("bridge")
    state.market.pop("XAUUSD", None)


def test_market_channel_is_rate_limited(client):
    with client.websocket_connect("/bridge/ws") as ws:
        ws.receive_json()
        sent = 0
        limited = False
        for _ in range(200):
            ws.send_text(json.dumps(_market_frame()))
            reply = ws.receive_json()
            if reply["msg"] == "market_ack":
                sent += 1
                continue
            limited = "rate limit" in reply["error"]
            break
        assert limited is True
        assert sent < 200
        assert ws is not None
    state.market.pop("XAUUSD", None)


def test_market_frame_is_refused_without_a_token(client, monkeypatch):
    monkeypatch.setenv("TRADERAIG_BRIDGE_TOKEN", "secret-token")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/bridge/ws") as ws:
            ws.receive_json()
            ws.send_text(json.dumps(_market_frame()))
            ws.receive_json()
    assert market_plane.quote("XAUUSD") is None


# -- file market transport ---------------------------------------------------

def test_market_frame_file_round_trip(tmp_path):
    bridge = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    assert bridge.market_directory == tmp_path / "market"
    assert bridge.write_market_frame(_market_frame()["payload"]) is True
    frames = bridge.read_market_frames()
    assert "XAUUSD" in frames
    assert frames["XAUUSD"]["quote"]["bid"] == 2399.5
    # a market frame never touches the signal file (single trade authority)
    assert not (tmp_path / "sig.json").exists()


def test_market_frame_write_requires_a_symbol(tmp_path):
    bridge = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    assert bridge.write_market_frame({"quote": {"bid": 1.0}}) is False
    assert bridge.read_market_frames() == {}


def test_unreadable_market_frame_is_skipped_not_guessed(tmp_path):
    bridge = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    bridge.write_market_frame(_market_frame()["payload"])
    (bridge.market_directory / "BROKEN.json").write_text("{not json",
                                                         encoding="utf-8")
    frames = bridge.read_market_frames()
    assert list(frames) == ["XAUUSD"]


def test_file_market_frames_are_ingested_as_a_bridge_source(tmp_path):
    from operations.market_bridge import MarketBridge

    plane = MarketPlane()
    br = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    br.write_market_frame(_market_frame()["payload"])
    mb = MarketBridge(bridge_source=br, plane=plane)
    result = mb.ingest_once()
    assert result == {"seen": 1, "ingested": 1, "bars": 1, "quotes": 1,
                      "rejected": 0, "shadowed": 0, "unchanged": 0}
    read = plane.read("XAUUSD", "M15", allow_pull=False)
    assert read.quote_source == "bridge:file"
    assert read.candles[-1].close == 2400.0
    st = mb.status()
    assert st["frames_ingested"] == 1 and st["active"] is False
    assert st["directory"].endswith("market")


def test_unchanged_market_frames_are_not_re_ingested(tmp_path):
    """An idle poller must not inflate 'ingested' counters.

    The plane upserts by bar time, so re-reading identical bytes is wasted work
    and, worse, makes `frames_ingested` claim terminal updates that never
    happened. A rewritten file is ingested again.
    """
    from operations.market_bridge import MarketBridge

    plane = MarketPlane()
    br = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    br.write_market_frame(_market_frame()["payload"])
    mb = MarketBridge(bridge_source=br, plane=plane)
    assert mb.ingest_once()["ingested"] == 1
    second = mb.ingest_once()
    assert second["ingested"] == 0 and second["unchanged"] == 1
    assert mb.status()["frames_ingested"] == 1
    assert mb.status()["frames_unchanged"] == 1
    # a real change on disk is picked up again
    br.write_market_frame(_market_frame(close=2401.0)["payload"])
    assert mb.ingest_once()["ingested"] == 1
    assert plane.read("XAUUSD", "M15", allow_pull=False).candles[-1].close == 2401.0


def test_file_market_frames_cannot_overwrite_an_mt5_owner(tmp_path):
    from operations.market_bridge import MarketBridge

    plane = MarketPlane()
    mt5 = MarketState(symbol="XAUUSD", bid=2700.0, ask=2701.0,
                      last_price=2700.5, last_tick_time=time.time())
    plane.publish_quote(mt5, source="mt5")
    plane.publish_candles("XAUUSD", "M15", [_bar(2700.5)], source="mt5")
    br = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    br.write_market_frame(_market_frame(close=2400.0)["payload"])
    result = MarketBridge(bridge_source=br, plane=plane).ingest_once()
    # the frame was seen and the quote attempted, but the plane refused it
    assert result["seen"] == 1
    assert plane.read("XAUUSD", "M15", allow_pull=False).quote is mt5
    assert plane.quote_shadow("XAUUSD")[-1]["source"] == "bridge:file"


def test_market_bridge_reports_rejections_honestly(tmp_path):
    from operations.market_bridge import MarketBridge

    plane = MarketPlane()
    br = MT5Bridge(filename="sig.json", directory=str(tmp_path))
    br.write_market_frame({"symbol": "XAUUSD", "quote": {"bid": 1.0}})
    mb = MarketBridge(bridge_source=br, plane=plane)
    result = mb.ingest_once()
    assert result["rejected"] == 1 and result["ingested"] == 0
    assert "bid and ask" in mb.status()["rejections"][-1]["reason"]
    assert plane.quote("XAUUSD") is None


def test_market_bridge_survives_a_missing_directory(tmp_path):
    from operations.market_bridge import MarketBridge

    mb = MarketBridge(bridge_source=MT5Bridge(directory=str(tmp_path / "nope")),
                      plane=MarketPlane())
    assert mb.ingest_once()["seen"] == 0
    assert mb.status()["last_error"] is None


def test_market_bridge_is_off_by_default(monkeypatch):
    from operations.market_bridge import MARKET_BRIDGE_ENV, MarketBridge

    monkeypatch.delenv(MARKET_BRIDGE_ENV, raising=False)
    assert MarketBridge.enabled_by_env() is False
    monkeypatch.setenv(MARKET_BRIDGE_ENV, "1")
    assert MarketBridge.enabled_by_env() is True


def test_app_lifespan_starts_the_market_bridge(monkeypatch):
    """The app that serves `/bridge/market` must also run its ingest.

    Regression: the poller only started in `main.py`, so booting the API the
    documented way (`uvicorn operations.api:app`, which is what the live smoke
    test does) reported `enabled_by_env: true, active: false` forever — the
    terminal market-file channel silently never ran.
    """
    from operations.market_bridge import MARKET_BRIDGE_ENV, market_bridge

    monkeypatch.setenv(MARKET_BRIDGE_ENV, "1")
    monkeypatch.setenv("MARKET_BRIDGE_INTERVAL", "0.5")
    try:
        with TestClient(api.app):
            assert market_bridge.status()["active"] is True
    finally:
        market_bridge.stop()
    assert market_bridge.status()["active"] is False


def test_app_lifespan_leaves_the_market_bridge_alone_when_disabled(monkeypatch):
    from operations.market_bridge import MARKET_BRIDGE_ENV, market_bridge

    monkeypatch.delenv(MARKET_BRIDGE_ENV, raising=False)
    before = market_bridge.status()["passes"]
    with TestClient(api.app):
        assert market_bridge.status()["active"] is False
        assert market_bridge.status()["passes"] == before


def test_bridge_market_endpoint_reports_real_ingest_state(client):
    st = client.get("/bridge/market").json()
    assert st["ok"] is True
    assert "frames_ingested" in st and "rejections" in st
    assert st["active"] in (True, False)
