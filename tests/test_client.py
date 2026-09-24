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


def test_plans_is_a_plain_get():
    """/v1/plans answers without a credential; the client still sends its key."""
    s = _Session([
        _Resp(200, {"data": {"currency": "USD", "plans": [{"key": "hobby"}],
                             "mcp": {"url": "https://api.ufcalendar.com/mcp"}}})
    ])
    api = FightAPI("ufcalendar_test", session=s)
    data = api.plans()
    assert s.calls[0][0] == "GET"
    assert s.calls[0][1].endswith("/v1/plans")
    assert data["plans"][0]["key"] == "hobby"
    assert data["mcp"]["url"].endswith("/mcp")


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


def test_fight_scorecards_unwraps_the_card():
    s = _Session([
        _Resp(200, {"data": {
            "fight_id": 83379, "fighter_a_id": 11402, "fighter_b_id": 9166,
            "decision_type": "split", "deductions": [],
            "cards": [{"judge_id": 36, "judge_name": "Vito Paolillo",
                       "total_a": 28, "total_b": 29, "winner_fighter_id": 9166,
                       "is_draw": False, "scores_known": True,
                       "rounds": [{"round": 1, "a": 9, "b": 10}]}],
        }}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    out = api.fight_scorecards(83379)
    assert s.calls[0][1].endswith("/v1/fights/83379/scorecards")
    assert out["decision_type"] == "split"
    assert out["cards"][0]["winner_fighter_id"] == 9166


def test_judges_paginates_and_drops_none_params():
    s = _Session([
        _Resp(200, {"data": [{"id": 5, "name": "Sal D'Amato"}],
                    "meta": {"pagination": {"next_cursor": "c2"}}}),
        _Resp(200, {"data": [{"id": 7, "name": "Derek Cleary"}],
                    "meta": {"pagination": {"next_cursor": None}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.judges(org="ufc", min_fights=10))
    assert [r["id"] for r in rows] == [5, 7]
    # q is None and must not be sent at all
    assert s.calls[0][2] == {"org": "ufc", "min_fights": 10, "limit": 100}
    assert s.calls[1][2]["cursor"] == "c2"


def test_judge_scorecards_path():
    s = _Session([
        _Resp(200, {"data": [{"fight_id": 1, "card": {"judge_id": 36}}],
                    "meta": {"pagination": {"next_cursor": None}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.judge_scorecards(36))
    assert s.calls[0][1].endswith("/v1/judges/36/scorecards")
    assert rows[0]["card"]["judge_id"] == 36


def test_fighter_include_is_a_comma_list():
    s = _Session([_Resp(200, {"data": {"id": 2215, "next_fight": None,
                                       "bonuses": {"org": "ufc", "total": 6}}})])
    api = FightAPI("ufcalendar_test", session=s)
    f = api.fighter("charles-oliveira-3", include=["bonuses"])
    assert s.calls[0][1].endswith("/v1/fighters/charles-oliveira-3")
    assert s.calls[0][2] == {"include": "bonuses"}
    assert f["bonuses"]["total"] == 6


def test_fighter_without_include_sends_no_params():
    s = _Session([_Resp(200, {"data": {"id": 1}})])
    api = FightAPI("ufcalendar_test", session=s)
    api.fighter("1")
    assert s.calls[0][2] == {}


def test_rankings_meta_exposes_neighbour_snapshots():
    s = _Session([_Resp(200, {
        "data": {"snapshot_date": "2016-11-07", "divisions": [
            {"division": "lightweight", "entries": [{"rank": 1, "movement": 2, "is_new": False, "country_code": "US"}]}]},
        "meta": {"previous_snapshot_date": "2016-10-12", "next_snapshot_date": "2016-11-16"},
    })])
    api = FightAPI("ufcalendar_test", session=s)
    board = api.rankings("ufc", date="2016-11-14")
    assert board["divisions"][0]["entries"][0]["movement"] == 2
    assert api.last_meta == {"previous_snapshot_date": "2016-10-12", "next_snapshot_date": "2016-11-16"}


def test_power_index_sends_view_division_days():
    s = _Session([_Resp(200, {"data": [{"position": 1, "delta": 43, "division": "welterweight"}],
                              "meta": {"view": "movers", "days": 730}})])
    api = FightAPI("ufcalendar_test", session=s)
    rows = api.power_index("ufc", view="movers", division="welterweight", days=730, limit=5)
    assert s.calls[0][1].endswith("/v1/power-index/ufc")
    assert s.calls[0][2] == {"view": "movers", "division": "welterweight", "days": 730, "limit": 5}
    assert rows[0]["delta"] == 43
    assert api.last_meta["days"] == 730


def test_power_index_bare_call_sends_no_params():
    s = _Session([_Resp(200, {"data": []})])
    api = FightAPI("ufcalendar_test", session=s)
    api.power_index()
    assert s.calls[0][2] == {}


def test_predictions_upcoming_narrows_by_event():
    s = _Session([_Resp(200, {"data": [], "meta": {"event": {"id": 8, "slug": "ufc-320"}}})])
    api = FightAPI("ufcalendar_test", session=s)
    api.predictions_upcoming(event="ufc-320")
    assert s.calls[0][2] == {"event": "ufc-320"}


def test_events_title_card_ppv_and_headline():
    s = _Session([_Resp(200, {"data": [{"slug": "a", "headline": {"fight_id": 185}}],
                              "meta": {"pagination": {"next_cursor": None}}})])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.events(org="ufc", is_title_card=True, is_ppv=False, include=["headline"]))
    assert s.calls[0][2] == {"org": "ufc", "is_title_card": "true", "is_ppv": "false",
                             "include": "headline", "limit": 100}
    assert rows[0]["headline"]["fight_id"] == 185


def test_event_include_eta():
    s = _Session([_Resp(200, {"data": {"slug": "ufc-320", "card": [{"id": 1, "eta": "2026-10-05T02:00:00.000Z"}]}})])
    api = FightAPI("ufcalendar_test", session=s)
    e = api.event("ufc-320", include=["eta"])
    assert s.calls[0][2] == {"include": "eta"}
    assert e["card"][0]["eta"] == "2026-10-05T02:00:00.000Z"


def test_event_without_include_sends_no_params():
    s = _Session([_Resp(200, {"data": {"slug": "ufc-320"}})])
    api = FightAPI("ufcalendar_test", session=s)
    api.event("ufc-320")
    assert s.calls[0][2] == {}


def test_find_fights_maps_filters_to_query_params():
    s = _Session([_Resp(200, {"data": [{"id": 185, "event": {"slug": "ufc-2026-06-14"}}],
                              "meta": {"pagination": {"next_cursor": None}}})])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.find_fights(org="ufc", title_only=True, method="ko", winner=100,
                                from_date="2020-01-01", order="oldest"))
    assert s.calls[0][1].endswith("/v1/fights/search")
    assert s.calls[0][2] == {"org": "ufc", "title_only": "true", "method": "ko", "winner": "100",
                             "from": "2020-01-01", "order": "oldest", "limit": 100}
    assert rows[0]["event"]["slug"] == "ufc-2026-06-14"


def test_changes_paginates_the_feed():
    s = _Session([
        _Resp(200, {"data": [{"id": 9, "kind": "fight-added"}], "meta": {"pagination": {"next_cursor": "c2"}}}),
        _Resp(200, {"data": [{"id": 8, "kind": "time-changed"}], "meta": {"pagination": {"next_cursor": None}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.changes(org="ufc", since="2026-09-01"))
    assert [r["id"] for r in rows] == [9, 8]
    assert s.calls[0][1].endswith("/v1/changes")
    assert s.calls[0][2] == {"org": "ufc", "since": "2026-09-01", "limit": 100}
    assert s.calls[1][2]["cursor"] == "c2"


def test_event_watch_passes_country():
    s = _Session([_Resp(200, {"data": {"series": None, "countries": [{"country": "WORLD", "providers": []}]}})])
    api = FightAPI("ufcalendar_test", session=s)
    out = api.event_watch("ufc-320", country="US")
    assert s.calls[0][1].endswith("/v1/events/ufc-320/watch")
    assert s.calls[0][2] == {"country": "US"}
    assert out["countries"][0]["country"] == "WORLD"


def test_broadcast_rights_passes_series():
    s = _Session([_Resp(200, {"data": []})])
    api = FightAPI("ufcalendar_test", session=s)
    api.broadcast_rights("ufc", series="dwcs")
    assert s.calls[0][1].endswith("/v1/broadcast-rights/ufc")
    assert s.calls[0][2] == {"series": "dwcs"}


def test_venues_and_venue_events_paginate():
    s = _Session([
        _Resp(200, {"data": [{"id": 5, "name": "T-Mobile Arena"}], "meta": {"pagination": {"next_cursor": None}}}),
        _Resp(200, {"data": [{"id": 71, "slug": "ufc-326"}], "meta": {"pagination": {"next_cursor": None}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    venues = list(api.venues("T-Mobile", country="US"))
    assert venues[0]["id"] == 5
    assert s.calls[0][1].endswith("/v1/venues")
    assert s.calls[0][2] == {"q": "T-Mobile", "country": "US", "limit": 100}
    events = list(api.venue_events(5, status="completed", from_date="2020-01-01"))
    assert events[0]["id"] == 71
    assert s.calls[1][1].endswith("/v1/venues/5/events")
    assert s.calls[1][2] == {"status": "completed", "from": "2020-01-01", "limit": 100}


def test_split_decisions_paginates():
    s = _Session([_Resp(200, {"data": [{"id": 184, "decision_type": "split", "dissenting_judges": [{"judge_id": 35}]}],
                              "meta": {"pagination": {"next_cursor": None}}})])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.split_decisions("ufc", to_date="2026-09-01"))
    assert s.calls[0][1].endswith("/v1/scorecards/splits")
    assert s.calls[0][2] == {"org": "ufc", "to": "2026-09-01", "limit": 100}
    assert rows[0]["dissenting_judges"][0]["judge_id"] == 35


def test_leaderboard_sends_org_and_metric():
    s = _Session([_Resp(200, {"data": [{"rank": 1, "value": 28, "tied": False}],
                              "meta": {"metric": {"slug": "wins", "unit": "count"}}})])
    api = FightAPI("ufcalendar_test", session=s)
    rows = api.leaderboard("ufc", "wins", division="lightweight", limit=5)
    assert s.calls[0][1].endswith("/v1/stats/leaders")
    assert s.calls[0][2] == {"org": "ufc", "metric": "wins", "division": "lightweight", "limit": 5}
    assert rows[0]["value"] == 28
    assert api.last_meta["metric"]["unit"] == "count"


def test_record_book_and_org_division():
    s = _Session([
        _Resp(200, {"data": [{"category": "records", "boards": []}]}),
        _Resp(200, {"data": {"org": "ufc", "division": {"slug": "lightweight"}, "rankings": None}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    book = api.record_book("ufc", scope="single_fight", top=3)
    assert s.calls[0][1].endswith("/v1/stats/record-book")
    assert s.calls[0][2] == {"org": "ufc", "scope": "single_fight", "top": 3}
    assert book[0]["category"] == "records"
    div = api.org_division("ufc", "lightweight")
    assert s.calls[1][1].endswith("/v1/orgs/ufc/divisions/lightweight")
    assert div["division"]["slug"] == "lightweight"


def test_compare_sends_both_fighters():
    s = _Session([_Resp(200, {"data": {"a": {"slug": "islam-makhachev"}, "b": {"slug": "charles-oliveira"},
                                       "win_streak": {"a": 16, "b": 1}, "prediction": None},
                              "meta": {"note": "not betting advice"}})])
    api = FightAPI("ufcalendar_test", session=s)
    cmp = api.compare("islam-makhachev", "charles-oliveira")
    assert s.calls[0][1].endswith("/v1/compare")
    assert s.calls[0][2] == {"a": "islam-makhachev", "b": "charles-oliveira"}
    assert cmp["win_streak"]["a"] == 16


def test_event_storylines_and_year_stats():
    s = _Session([
        _Resp(200, {"data": {"summary": {"title_fights": 2}, "fights": [], "card": {}}}),
        _Resp(200, {"data": {"year": 2025, "orgs_scope": ["ufc"], "events_completed": 47}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    st = api.event_storylines("ufc-322-2025-11-15")
    assert s.calls[0][1].endswith("/v1/events/ufc-322-2025-11-15/storylines")
    assert st["summary"]["title_fights"] == 2
    yr = api.year_stats(2025, org="ufc")
    assert s.calls[1][1].endswith("/v1/stats/years/2025")
    assert s.calls[1][2] == {"org": "ufc"}
    assert yr["orgs_scope"] == ["ufc"]


def test_event_pickem_and_fighter_credentials():
    s = _Session([
        _Resp(200, {"data": {"event": {"slug": "ufc-322-2025-11-15"},
                             "fights": [{"fight_id": 591, "picks_a": 3, "picks_b": 1, "total": 4, "pct_a": 75.0}]},
                    "meta": {"note": "crowd sentiment"}}),
        _Resp(200, {"data": {"slug": "islam-makhachev",
                             "credentials": {"credentials": [], "affiliations": [
                                 {"kind": "gym", "name": "AKA", "sources": ["https://x"], "confidence": "reported"}]}}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    pk = api.event_pickem("ufc-322-2025-11-15")
    assert s.calls[0][1].endswith("/v1/events/ufc-322-2025-11-15/pickem")
    assert pk["fights"][0]["pct_a"] == 75.0
    f = api.fighter("islam-makhachev", include=["bonuses", "credentials"])
    assert s.calls[1][2] == {"include": "bonuses,credentials"}
    assert f["credentials"]["affiliations"][0]["confidence"] == "reported"


def test_articles_pages_and_article_reads_one():
    s = _Session([
        _Resp(200, {"data": [{"slug": "a"}], "meta": {"pagination": {"next_cursor": "C2", "has_more": True}}}),
        _Resp(200, {"data": [{"slug": "b"}], "meta": {"pagination": {"next_cursor": None, "has_more": False}}}),
        _Resp(200, {"data": {"slug": "a", "body_md": "# A", "served_locale": "en"}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    rows = list(api.articles("title fight", locale="es"))
    assert [r["slug"] for r in rows] == ["a", "b"]
    assert s.calls[0][1].endswith("/v1/articles")
    assert s.calls[0][2]["q"] == "title fight" and s.calls[0][2]["locale"] == "es"
    assert s.calls[1][2]["cursor"] == "C2"
    art = api.article("a", locale="es")
    assert s.calls[2][1].endswith("/v1/articles/a")
    assert s.calls[2][2] == {"locale": "es"}
    assert art["served_locale"] == "en"


def test_matchmaker_and_whos_next():
    s = _Session([
        _Resp(200, {"data": [{"key": "1-2", "division": "lightweight", "score": 91, "win_probability_a": 0.61}],
                    "meta": {"org": "ufc", "division": "lightweight", "divisions": ["lightweight"]}}),
        _Resp(200, {"data": {"subject": {"slug": "islam-makhachev"}, "division": "welterweight",
                             "suggestions": [{"opponent": {"slug": "x"}, "win_probability_subject": 0.62, "score": 88}],
                             "booked_next": None}}),
    ])
    api = FightAPI("ufcalendar_test", session=s)
    board = api.matchmaker("ufc", division="lightweight", limit=5)
    assert s.calls[0][1].endswith("/v1/matchmaker/ufc")
    assert s.calls[0][2] == {"division": "lightweight", "limit": 5}
    assert board[0]["score"] == 91
    assert api.last_meta["divisions"] == ["lightweight"]
    nxt = api.whos_next("islam-makhachev")
    assert s.calls[1][1].endswith("/v1/matchmaker/next/islam-makhachev")
    assert nxt["suggestions"][0]["score"] == 88
