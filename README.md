# ufcalendar — Python client for the UFCalendar Fight API

The [UFCalendar Fight API](https://www.ufcalendar.com/developers) is a REST API for MMA data: **UFC, PFL, OKTAGON, BKFC and RIZIN** events, full fight cards, results within minutes, per-fight and round-by-round statistics, complete fighter careers, the only **MMA data API with point-in-time UFC rankings history back to 2013**, and the only one serving **judges' scorecards** — every official, every round: UFC back to 1995, PFL to 2018, OKTAGON to 2025 and RIZIN from March 2026 — plus the **UFCalendar consensus odds line** (current, opening and closing on every plan, line movement on Pro). This package is a thin `requests` wrapper over it — one method per endpoint, cursor pagination handled for you.

```bash
pip install ufcalendar
```

Get a key (free 1-day trial, 100 requests, no card) at https://www.ufcalendar.com/account/api?trial=1. Paid plans from $19/month for 30,000 requests (Pro $49 for 200,000, Business $149 for 1,000,000), hard caps, no overage.

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
| `plans()` | `GET /v1/plans` — plans, quotas, trial terms, MCP endpoint (no key required) |
| `events(org, status, from_date, to_date, order, is_title_card, is_ppv, include=["headline"])` | `GET /v1/events` (paginated; `headline` = each card's main event and its result) |
| `event(slug, include=["eta", "odds"])` / `event_changes(slug)` | `GET /v1/events/{slug}` / `…/changes` (`eta` = per-bout estimated start; `odds` = each bout's latest consensus line) |
| `event_watch(slug, country)` | `GET /v1/events/{slug}/watch` — how to watch one event, per country: the rights deals for its series merged with the event's own listings |
| `changes(org, since, kind)` | `GET /v1/changes` — the card-change feed across every event, newest first (paginated; default last 90 days) |
| `fight(id, include=["odds"])` / `fight_stats(id)` / `fight_rounds(id)` | `GET /v1/fights/{id}` / `…/stats` / `…/rounds` |
| `fight_odds(id)` / `event_odds(slug)` | `GET /v1/fights/{id}/odds` / `GET /v1/events/{slug}/odds` — the UFCalendar consensus line: current, opening, closing (settled bouts), movement and `sources` (how many sportsbooks backed each point). Information only, not betting advice |
| `fight_odds_history(id, from_date, to_date)` | `GET /v1/fights/{id}/odds/history` — every consensus point, oldest first (paginated; Pro plans and up) |
| `find_fights(org, title_only, method, division, fighter, winner, from_date, to_date, main_events_only, order)` | `GET /v1/fights/search` — completed bouts, filtered, newest first (at least one narrowing filter; 25 a page, 10 pages deep) |
| `fight_scorecards(id)` | `GET /v1/fights/{id}/scorecards` — judges, rounds, totals, deductions |
| `judges(q, org, min_fights)` / `judge(id)` / `judge_scorecards(id)` | `GET /v1/judges` / `…/{id}` / `…/{id}/scorecards` (`last_meta["league"]` = baseline rates; each card row flags `lone_dissent` / `split` and lists `colleagues`) |
| `split_decisions(org, from_date, to_date)` | `GET /v1/scorecards/splits` — split and majority decisions, newest first, with every judge's card and the dissenters named (paginated) |
| `fighters(q, org, country)` / `fighter(slug, include=["bonuses", "credentials"])` | `GET /v1/fighters` / `…/{slug}` (always carries `next_fight` / `last_fight`; `bonuses` = the UFC bonus ledger; `credentials` = grappling and wrestling pedigree, gyms and coaches, each row sourced and confidence-graded) |
| `fighter_history` / `fighter_stats` / `fighter_rankings` / `fighter_power_index` | `GET /v1/fighters/{slug}/…` |
| `rankings(org, date)` / `division_rankings(org, division)` / `champions()` | `GET /v1/rankings/…` / `/v1/champions` (entries carry `movement`, `is_new`, `country_code`; `last_meta` names the previous/next snapshot) |
| `power_index(org, view, division, days, limit)` / `predictions_upcoming(event)` | `GET /v1/power-index/{org}` (`view`: `current` · `movers` · `peaks`) / `/v1/predictions/upcoming` |
| `matchmaker(org, division, limit)` / `whos_next(fighter, limit)` | `GET /v1/matchmaker/{org}` / `…/next/{fighter}` — UFCalendar's matchmaker: the fights worth making (scored 0–100, per division or across the roster; not bookings), and one fighter's best next opponents with the win probability for each and the bout already booked |
| `leaderboard(org, metric, division, country, population, limit)` / `record_book(org, division, country, population, scope, top)` | `GET /v1/stats/leaders` / `…/record-book` — the Record Book: one leaderboard (48 metrics; ties flagged, sample size on every row), or every board's top rows grouped by category |
| `org_division(org, division)` | `GET /v1/orgs/{org}/divisions/{division}` — one weight class: rankings board, upcoming bouts, latest results, roster by recency |
| `year_stats(year, org)` | `GET /v1/stats/years/{year}` — one calendar year in numbers for one promotion (or every covered one): methods, divisions, fastest finishes, upsets, Power Index climbers, busiest fighters, countries, judges |
| `compare(a, b)` | `GET /v1/compare` — two fighters side by side: bios, career stats, strike mix, streaks, previous meetings, common opponents, booked bout, model prediction (UFC), Power Index |
| `event_storylines(slug)` | `GET /v1/events/{slug}/storylines` — the talking points of one card: title fights, eliminators, closest bout, rematches, streaks, debuts, returns, ranked fighters, nations |
| `event_pickem(slug)` | `GET /v1/events/{slug}/pickem` — how the UFCalendar community is picking each bout on one card (picks per corner, total, percentage); crowd sentiment, not a market and not a forecast |
| `broadcast_rights(org, country, series)` / `venue(id)` / `search(q)` / `usage()` | misc (`series="dwcs"`/`"rtufc"` = a UFC sub-series grid) |
| `venues(q, country)` / `venue_events(id, status, from_date, to_date, order)` | `GET /v1/venues` / `…/{id}/events` — venue search, and every covered event at one venue, newest first (paginated) |
| `articles(q, tag, locale)` / `article(slug, locale)` | `GET /v1/articles` / `…/{slug}` — UFCalendar's own editorial archive, newest first, in any of the 13 site languages (paginated), and one article's full Markdown body |
| `create_webhook_endpoint(url, events)` … | `POST /v1/webhook-endpoints` (Pro+; kinds `event.announced`, `fight.result`, `card.changed`, `event.completed`, `odds.moved`) |
| `calendar_ics_url(org)` | `GET /v1/calendar/{org}.ics` |

Full reference: https://api.ufcalendar.com/docs · OpenAPI 3.1: https://api.ufcalendar.com/openapi.json · Also on [npm (TypeScript client)](https://www.npmjs.com/package/@ufcalendar/sdk), [RapidAPI Hub](https://rapidapi.com/ceo-SP8r6F1JT/api/ufc-and-mma-fight-data-by-ufcalendar), [Postman](https://www.postman.com/ceo-5d84eedc/workspace/ufcalendar-fight-api) and the [hosted MCP server](https://github.com/UFCalendar/ufcalendar-mcp)

## Consensus odds

```python
o = api.fight_odds(83379)
print(o["consensus"]["a"]["american"], o["consensus"]["b"]["american"], o["consensus"]["sources"])
print(o["movement"]["delta_points_a"], o["closing"])   # closing = last line before the start (settled bouts)

for point in api.fight_odds_history(83379):               # Pro plans and up
    print(point["recorded_at"], point["a"]["american"], point["b"]["american"])
```

One anonymised UFCalendar consensus line per corner across the sportsbooks we track;
book identities are never exposed. Information only, not betting advice.

## Webhooks instead of polling (Pro and up)

```python
ep = api.create_webhook_endpoint("https://example.com/hooks/ufcal", ["fight.result", "card.changed"])
print(ep["secret"])   # shown once; verify X-UFCalendar-Signature with it
```

`odds.moved` fires when the consensus line on an upcoming bout moves 5+ implied-probability
points on corner a, or the favourite flips, measured against the last line delivered, so a
slow drift arrives once. Information only, not betting advice.

## Errors and rate limits

Every error raises `FightAPIError` with `.status`, `.code`, `.message`, `.request_id`. After each call `api.last_rate_limit` holds the `X-RateLimit-*` headers.

## Notes

- Odds are the UFCalendar consensus line only (no book identities). Information only, not betting advice.
- Fighter `images` are Wikimedia Commons / Creative Commons files: display the `license` and `artist` fields as a credit.
- Not affiliated with UFC, Zuffa, TKO or any promotion. Terms: https://www.ufcalendar.com/developers/terms

MIT licensed.
