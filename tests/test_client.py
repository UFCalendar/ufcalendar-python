"""Offline tests: the client's request shapes and error handling, no network."""

import json

import pytest
import requests

from ufcalendar import FightAPI, FightAPIError


class _Resp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw.get("params"), kw.get("json")))
        return self.responses.pop(0)


def test_requires_key(monkeypatch):
    monkeypatch.delenv("UFCAL_API_KEY", raising=False)
    with pytest.raises(ValueError):
        FightAPI()


def test_events_paginates_and_drops_none_params():
    s = _Session([
        _Resp(200, {"data": [{"slug": "a"}], "meta": {"pagination": {"next_cursor": "c2"}}}, {"X-RateLimit-Remaining": "99"}),
        _Resp(200, {"data": [{"slug": "b"}], "meta": {"pagination": {"next_cursor": None}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.events(org="ufc", status=None))
    assert [r["slug"] for r in rows] == ["a", "b"]
    assert s.calls[0][1].endswith("/v1/events")
    assert s.calls[0][2] == {"org": "ufc", "limit": 100}
    assert s.calls[1][2]["cursor"] == "c2"
    assert api.last_rate_limit["remaining"] is None  # last call carried no header


def test_rankings_date_param():
    s = _Session([_Resp(200, {"data": {"snapshot_date": "2016-11-07", "divisions": []}})])
    api = FightAPI("ufcalendar_test", session=s)
    board = api.rankings("ufc", date="2016-11-14")
    assert board["snapshot_date"] == "2016-11-07"
    assert s.calls[0][1].endswith("/v1/rankings/ufc")
    assert s.calls[0][2] == {"date": "2016-11-14"}


def test_error_envelope():
    s = _Session([_Resp(403, {"error": {"code": "subscription_required", "message": "no plan", "request_id": "req_1"}})])
    api = FightAPI("ufcalendar_test", session=s)
    with pytest.raises(FightAPIError) as ei:
        api.champions()
    assert ei.value.status == 403
    assert ei.value.code == "subscription_required"
    assert ei.value.request_id == "req_1"


def test_webhook_create_body():
    s = _Session([_Resp(201, {"data": {"id": 1, "secret": "whsec"}})])
    api = FightAPI("ufcalendar_test", session=s)
    ep = api.create_webhook_endpoint("https://example.com/h", ["fight.result"])
    assert ep["secret"] == "whsec"
    assert s.calls[0][0] == "POST"
    assert s.calls[0][3] == {"url": "https://example.com/h", "events": ["fight.result"]}


def test_ics_url_carries_key():
    api = FightAPI("ufcalendar_test", session=_Session([]))
    assert api.calendar_ics_url("ufc") == "https://api.ufcalendar.com/v1/calendar/ufc.ics?key=ufcalendar_test"
