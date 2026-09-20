"""Offline tests for FightAPI.live_stream — a fake socket, never a network call."""

import json

import pytest

from ufcalendar import FightAPI


class _FakeSocket:
    """Minimal stand-in for a websocket-client connection."""

    def __init__(self, frames):
        # Each entry is either a str/bytes frame or an Exception to raise.
        self._frames = list(frames)
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(payload)

    def recv(self):
        if not self._frames:
            raise ConnectionError("socket drained")
        item = self._frames.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def _connector(sockets, urls):
    def connect(url):
        urls.append(url)
        return sockets.pop(0)

    return connect


def _frame(type_, **kw):
    return json.dumps({"type": type_, **kw})


def test_live_stream_subscribes_and_yields_parsed_frames():
    urls = []
    sock = _FakeSocket([
        _frame("snapshot", data={"seq": 1}),
        _frame("update", data={"seq": 2}),
        _frame("fight.final", data={"seq": 3}),
    ])
    api = FightAPI("ufcalendar_test")
    frames = list(
        api.live_stream("ufc-331", until_final=True, connect=_connector([sock], urls))
    )

    assert urls == ["wss://live.ufcalendar.com/v1?key=ufcalendar_test"]
    assert json.loads(sock.sent[0]) == {"action": "subscribe", "event": "ufc-331"}
    assert [f["type"] for f in frames] == ["snapshot", "update", "fight.final"]
    assert frames[1]["data"] == {"seq": 2}
    assert sock.closed is True


def test_live_stream_without_until_final_keeps_going_past_a_final():
    urls = []
    sock = _FakeSocket([
        _frame("fight.final", data={"seq": 1}),
        _frame("update", data={"seq": 2}),
    ])
    api = FightAPI("ufcalendar_test")
    gen = api.live_stream("ufc-331", connect=_connector([sock], urls))
    got = [next(gen), next(gen)]
    gen.close()
    assert [f["type"] for f in got] == ["fight.final", "update"]


def test_live_stream_reconnects_once_then_gives_up():
    urls = []
    first = _FakeSocket([_frame("snapshot", data=None), ConnectionError("dropped")])
    second = _FakeSocket([_frame("update", data={"seq": 9}), ConnectionError("dropped again")])
    api = FightAPI("ufcalendar_test")
    gen = api.live_stream("ufc-331", connect=_connector([first, second], urls))

    assert next(gen)["type"] == "snapshot"
    assert next(gen)["type"] == "update"  # survived the first drop
    with pytest.raises(ConnectionError):
        next(gen)

    assert len(urls) == 2, "reconnected exactly once"
    assert json.loads(second.sent[0])["action"] == "subscribe", "re-subscribed after reconnect"
    assert first.closed and second.closed


def test_live_stream_skips_unparseable_frames():
    sock = _FakeSocket(["not json", _frame("update", data={"seq": 1}), ConnectionError("end")])
    api = FightAPI("ufcalendar_test")
    gen = api.live_stream("ufc-331", connect=_connector([sock, _FakeSocket([ConnectionError("end")])], []))
    assert next(gen)["type"] == "update"
    gen.close()


def test_live_stream_without_the_optional_dependency_explains_the_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_websocket(name, *a, **kw):
        if name == "websocket":
            raise ImportError("No module named 'websocket'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_websocket)
    api = FightAPI("ufcalendar_test")
    with pytest.raises(ImportError) as exc:
        next(api.live_stream("ufc-331"))
    assert "ufcalendar[live]" in str(exc.value)
