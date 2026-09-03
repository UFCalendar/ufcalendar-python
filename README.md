# ufcalendar — Python client for the UFCalendar Fight API

The [UFCalendar Fight API](https://www.ufcalendar.com/developers) is a REST API for MMA data: **UFC, PFL, OKTAGON and BKFC** events, full fight cards, results within minutes, per-fight and round-by-round statistics, complete fighter careers, and the only **UFC rankings API with point-in-time history back to 2013**. This package is a thin `requests` wrapper over it — one method per endpoint, cursor pagination handled for you.

```bash
pip install ufcalendar
```

Get a key (free 1-day trial, 100 requests, no card) at https://www.ufcalendar.com/account/api?trial=1. Paid plans from $19/month, hard caps, no overage.

## Quickstart

```python
from ufcalendar import FightAPI

api = FightAPI("ufcalendar_...")            # or export UFCAL_API_KEY=...

# Upcoming UFC schedule, soonest first
for ev in api.events(org="ufc", limit=5):
    print(ev["starts_at"], ev["title"], "PPV" if ev["is_ppv"] else "")

# Full card + results of the newest completed UFC event
latest = next(api.events(org="ufc", status="completed", limit=1))
card = api.event(latest["slug"])
for f in card["fights"]:
    r = f.get("result")
    if r:
        print(f["fighter_a"]["name"], "vs", f["fighter_b"]["name"], "->", r["method"], f"R{r['round']} {r['time']}")

# Round-by-round statistics for one bout
rounds = api.fight_rounds(card["fights"][0]["id"])

# UFC rankings on any date since February 2013 (rank 0 = champion)
board = api.rankings("ufc", date="2016-11-14")
lw = next(d for d in board["divisions"] if d["division"] == "lightweight")
print(board["snapshot_date"], [e["name"] for e in lw["entries"][:5]])

# A fighter's complete multi-promotion career
history = api.fighter_history("islam-makhachev")
```

## What's covered

| Method | Endpoint |
|---|---|
| `events(org, status, from_date, to_date, order)` | `GET /v1/events` (paginated) |
| `event(slug)` / `event_changes(slug)` | `GET /v1/events/{slug}` / `…/changes` |
| `fight(id)` / `fight_stats(id)` / `fight_rounds(id)` | `GET /v1/fights/{id}` / `…/stats` / `…/rounds` |
| `fighters(q, org, country)` / `fighter(slug)` | `GET /v1/fighters` / `…/{slug}` |
| `fighter_history` / `fighter_stats` / `fighter_rankings` / `fighter_power_index` | `GET /v1/fighters/{slug}/…` |
| `rankings(org, date)` / `division_rankings(org, division)` / `champions()` | `GET /v1/rankings/…` / `/v1/champions` |
| `power_index(org)` / `predictions_upcoming()` | `GET /v1/power-index/{org}` / `/v1/predictions/upcoming` |
| `broadcast_rights(org, country)` / `venue(id)` / `search(q)` / `usage()` | misc |
| `create_webhook_endpoint(url, events)` … | `POST /v1/webhook-endpoints` (Pro+) |
| `calendar_ics_url(org)` | `GET /v1/calendar/{org}.ics` |

Full reference: https://api.ufcalendar.com/docs · OpenAPI 3.1: https://api.ufcalendar.com/openapi.json

## Webhooks instead of polling (Pro and up)

```python
ep = api.create_webhook_endpoint("https://example.com/hooks/ufcal", ["fight.result", "card.changed"])
print(ep["secret"])   # shown once; verify X-UFCalendar-Signature with it
```

## Errors and rate limits

Every error raises `FightAPIError` with `.status`, `.code`, `.message`, `.request_id`. After each call `api.last_rate_limit` holds the `X-RateLimit-*` headers.

## Notes

- No betting odds are served, by design.
- Fighter `images` are Wikimedia Commons / Creative Commons files: display the `license` and `artist` fields as a credit.
- Not affiliated with UFC, Zuffa, TKO or any promotion. Terms: https://www.ufcalendar.com/developers/terms

MIT licensed.
