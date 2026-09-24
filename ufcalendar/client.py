"""Thin, dependency-light client for https://api.ufcalendar.com/v1.

Every method returns the parsed ``data`` value of the JSON envelope
(``{"data": ..., "meta": ...}``); list endpoints are generators that follow
cursor pagination for you. Errors raise :class:`FightAPIError` carrying the
API's ``code``, ``message`` and ``request_id`` (quote the request id when
you write to api@ufcalendar.com).

Odds are the UFCalendar consensus line: one anonymised line per corner across
the sportsbooks we track (``sources`` = how many books backed each point; book
identities are never exposed). Information only, not betting advice. Fighter
``images`` are Wikimedia
Commons / Creative Commons files — the ``license`` and ``artist`` fields you
receive must be displayed as a credit.
"""

from __future__ import annotations

import contextlib
import json as _json
import os
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence
from urllib.parse import quote

import requests

DEFAULT_BASE_URL = "https://api.ufcalendar.com/v1"
#: The live WebSocket (UFC fight nights, Pro plans and up). Same document as
#: ``GET /v1/events/{id}/live``, pushed on every change.
LIVE_WS_URL = "wss://live.ufcalendar.com/v1"
_TIMEOUT = 30


class FightAPIError(Exception):
    """An error response from the Fight API."""

    def __init__(self, status: int, code: str, message: str, request_id: Optional[str] = None):
        super().__init__(f"{status} {code}: {message}" + (f" (request_id={request_id})" if request_id else ""))
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id


def _connect_websocket(url: str) -> Any:
    """Open the live socket with the optional ``websocket-client`` dependency."""
    try:
        from websocket import create_connection  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised with a patched import
        raise ImportError(
            "live_stream() needs a WebSocket client, which ships as an optional extra. "
            "Install it with: pip install 'ufcalendar[live]'"
        ) from exc
    return create_connection(url, timeout=_TIMEOUT)


def _bool_param(v: Optional[bool]) -> Optional[str]:
    """``True`` → ``"true"`` (requests would send ``"True"``); None drops the param."""
    return None if v is None else ("true" if v else "false")


class FightAPI:
    """Client for the UFCalendar Fight API.

    :param api_key: ``ufcalendar_…`` key from https://www.ufcalendar.com/account/api.
        Falls back to the ``UFCAL_API_KEY`` environment variable.
    :param base_url: override for testing; defaults to the production ``/v1``.
    :param session: optional :class:`requests.Session` to reuse connections.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = _TIMEOUT,
    ):
        key = api_key or os.environ.get("UFCAL_API_KEY")
        if not key:
            raise ValueError(
                "No API key. Pass api_key=... or set UFCAL_API_KEY. "
                "Keys (and the free 1-day trial) live at https://www.ufcalendar.com/account/api"
            )
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout
        self.last_rate_limit: Dict[str, Optional[str]] = {"limit": None, "remaining": None, "reset": None}
        #: ``meta`` of the most recent response (pagination cursor, neighbour snapshot dates …).
        self.last_meta: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ core

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json: Any = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self._session.request(
            method,
            url,
            params=clean,
            json=json,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "ufcalendar-python/0.7.1",
            },
            timeout=self._timeout,
            allow_redirects=True,
        )
        self.last_rate_limit = {
            "limit": resp.headers.get("X-RateLimit-Limit"),
            "remaining": resp.headers.get("X-RateLimit-Remaining"),
            "reset": resp.headers.get("X-RateLimit-Reset"),
        }
        if resp.status_code == 204:
            self.last_meta = None
            return {}
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            self.last_meta = None
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                raise FightAPIError(resp.status_code, str(err.get("code", "error")), str(err.get("message", resp.text[:200])), err.get("request_id"))
            raise FightAPIError(resp.status_code, "http_error", resp.text[:200], resp.headers.get("x-request-id"))
        self.last_meta = body.get("meta") if isinstance(body, dict) else None
        return body

    def get(self, path: str, **params: Any) -> Any:
        """Raw GET returning the ``data`` value. Escape hatch for new endpoints."""
        return self._request("GET", path, params).get("data")

    def _paginate(self, path: str, params: Dict[str, Any], limit: Optional[int]) -> Iterator[Dict[str, Any]]:
        params = dict(params)
        params.setdefault("limit", 100)
        seen = 0
        while True:
            body = self._request("GET", path, params)
            for row in body.get("data") or []:
                yield row
                seen += 1
                if limit is not None and seen >= limit:
                    return
            cursor = ((body.get("meta") or {}).get("pagination") or {}).get("next_cursor")
            if not cursor:
                return
            params["cursor"] = cursor

    # ----------------------------------------------------------------- plans

    def plans(self) -> Dict[str, Any]:
        """Plans, quotas, the free 1-day trial rule, the MCP endpoint and the doc links.

        The only endpoint that answers without a credential (the client still
        sends its key header — harmless). Useful for showing a caller what a
        higher tier would buy them before they upgrade.
        """
        return self.get("plans")

    # ------------------------------------------------------------------ orgs

    def orgs(self) -> List[Dict[str, Any]]:
        """Launch orgs with capability flags (stats / rounds / rankings / broadcasts / predictions / scorecards / odds)."""
        return self.get("orgs")

    def org(self, slug: str) -> Dict[str, Any]:
        return self.get(f"orgs/{slug}")

    def org_division(self, org: str, division: str) -> Dict[str, Any]:
        """One weight class in one promotion: its rankings board (``None`` where
        the promotion publishes none), upcoming bouts at that weight, the latest
        results and the roster by recency. ``division`` is a slug, e.g.
        ``"lightweight"`` or ``"womens-strawweight"``."""
        return self.get(f"orgs/{org}/divisions/{division}")

    # ---------------------------------------------------------------- events

    def events(
        self,
        org: Optional[str] = None,
        *,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: Optional[str] = None,
        is_title_card: Optional[bool] = None,
        is_ppv: Optional[bool] = None,
        include: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Schedule + results. Bare call = upcoming calendar, soonest first.

        ``status="completed"`` (or ``order="desc"``) browses the archive newest-first.
        ``from_date`` / ``to_date`` are ``YYYY-MM-DD``. ``is_title_card`` /
        ``is_ppv`` filter the cards; ``include=["headline"]`` adds each card's
        main event (and its result once fought).
        """
        return self._paginate(
            "events",
            {
                "org": org,
                "status": status,
                "from": from_date,
                "to": to_date,
                "order": order,
                "is_title_card": _bool_param(is_title_card),
                "is_ppv": _bool_param(is_ppv),
                "include": ",".join(include) if include else None,
            },
            limit,
        )

    def event(self, id_or_slug: str, *, include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """One event with its full fight card, venue and broadcasts.
        ``include=["eta"]`` adds an estimated start time to every bout;
        ``include=["odds"]`` adds each bout's current UFCalendar consensus line
        (``None`` when unpriced). Pass both as ``["eta", "odds"]``."""
        return self.get(f"events/{id_or_slug}", include=",".join(include) if include else None)

    def event_watch(self, id_or_slug: str, *, country: Optional[str] = None) -> Dict[str, Any]:
        """Who airs one event, per country: the promotion's rights deals for the
        event's series merged with the event's own listings. ``country`` (ISO-2)
        narrows to that market plus worldwide."""
        return self.get(f"events/{id_or_slug}/watch", country=country)

    def event_storylines(self, id_or_slug: str) -> Dict[str, Any]:
        """The talking points of one card as of its start: ``summary`` (title
        fights, ranked fighters, champions, the closest bout), per-bout ``tags``
        (title, eliminator, coin_flip, both_streaking, finishers, rematch,
        trilogy_decider) with ranks, signed streaks and a win probability
        (UFCalendar model, else Power Index — not betting advice), and ``card``
        aggregates (average age, tallest, longest reach, nations, streak
        leaders, debuts, returns, fastest career finish)."""
        return self.get(f"events/{id_or_slug}/storylines")

    def event_pickem(self, id_or_slug: str) -> Dict[str, Any]:
        """How the UFCalendar community is picking each bout on one card:
        ``picks_a``, ``picks_b``, ``total`` and ``pct_a`` (percentage on corner
        a; ``None`` when nobody picked), in card order. Crowd sentiment from
        our own pick'em game, not a market and not a forecast."""
        return self.get(f"events/{id_or_slug}/pickem")

    def event_odds(self, id_or_slug: str) -> Dict[str, Any]:
        """The UFCalendar consensus odds for every non-cancelled bout on one
        card, in card order: ``consensus`` (latest point; the closing line once settled), ``opening``,
        ``closing`` (settled bouts), ``movement`` and ``points``. Unpriced
        bouts stay on the list with ``None`` and ``points == 0``;
        ``last_meta["priced"]`` / ``["unpriced"]`` count both. Consensus
        across the sportsbooks we track, book identities never exposed.
        Information only, not betting advice."""
        return self.get(f"events/{id_or_slug}/odds")

    def event_changes(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Card-change diff log (fight added/removed, opponent swapped, date moved, fighter profile merged)."""
        return self.get(f"events/{id_or_slug}/changes")

    def changes(
        self,
        org: Optional[str] = None,
        *,
        since: Optional[str] = None,
        kind: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """The card-change feed across every event, newest first (default: last 90 days).

        The ``card.changed`` webhook's audit trail, for callers that poll.
        ``since`` is ``YYYY-MM-DD`` or an ISO-8601 datetime; ``kind`` narrows
        to one of fight-added, fight-cancelled, fight-reinstated,
        opponent-changed, time-changed, venue-changed, fighter-merged. Each
        row carries its ``event`` (id, slug, title, org, starts_at).
        """
        return self._paginate("changes", {"org": org, "since": since, "kind": kind}, limit)

    def event_live(self, id_or_slug: str) -> Optional[Dict[str, Any]]:
        """Latest real-time LiveState snapshot on fight night (Pro plans and up),
        or None when nothing is being streamed. The WebSocket at
        wss://live.ufcalendar.com/v1 pushes the same document as it changes —
        see :meth:`live_stream`."""
        return self.get(f"events/{id_or_slug}/live")

    def live_stream(
        self,
        event: str,
        *,
        until_final: bool = False,
        url: str = LIVE_WS_URL,
        connect: Optional[Callable[[str], Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Subscribe to the live WebSocket and yield every frame (Pro plans and up).

        The UFC live API: connects to ``wss://live.ufcalendar.com/v1?key=…``,
        sends ``{"action": "subscribe", "event": <slug>}`` and yields each
        frame as a dict — ``{"type": "snapshot" | "update" | "fight.final" |
        "event.completed", "data": <LiveState>}``. ``data`` carries the round,
        the running clock, unofficial in-fight statistics and the action
        timeline: the same document :meth:`event_live` returns as a snapshot.

            for frame in api.live_stream("ufc-331", until_final=True):
                print(frame["type"])

        :param event: event slug, our event id, or the UFC fmid.
        :param until_final: stop after the first ``fight.final`` frame.
            Default False — the generator runs until the socket ends.
        :param connect: inject a connector for tests. Defaults to
            ``websocket.create_connection`` from the optional ``websocket-client``
            dependency: ``pip install 'ufcalendar[live]'``.

        A dropped socket is reconnected (and re-subscribed) ONCE; a second
        drop raises, so a caller that wants an all-night ticker should wrap
        this in its own retry loop.
        """
        opener = connect or _connect_websocket
        target = f"{url}?key={quote(self.api_key, safe='')}"
        reconnects = 0
        while True:
            sock = opener(target)
            try:
                sock.send(_json.dumps({"action": "subscribe", "event": event}))
                while True:
                    raw = sock.recv()
                    if raw is None or raw == "" or raw == b"":
                        raise ConnectionError("live stream closed by the server")
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", "replace")
                    try:
                        frame = _json.loads(raw)
                    except ValueError:
                        continue  # a half-frame is not worth killing the night over
                    if not isinstance(frame, dict):
                        continue
                    yield frame
                    if until_final and frame.get("type") == "fight.final":
                        return
            except GeneratorExit:
                raise
            except Exception:
                if reconnects >= 1:
                    raise
                reconnects += 1
            finally:
                with contextlib.suppress(Exception):
                    sock.close()

    # ---------------------------------------------------------------- fights

    def fight(self, fight_id: int, *, include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """One bout with its result and a compact ``event``.
        ``include=["odds"]`` adds ``odds``: the current consensus line (the closing line once the bout is settled) (or ``None``)."""
        return self.get(f"fights/{fight_id}", include=",".join(include) if include else None)

    def fight_odds(self, fight_id: int) -> Dict[str, Any]:
        """The UFCalendar consensus line for one bout.

        ``consensus`` is the latest point (the closing line once the bout is settled), ``opening`` the first we recorded,
        ``closing`` the last point at or before the event start (settled bouts
        only), ``movement`` the opening → consensus shift in implied-probability
        points on corner a. Every point carries ``a`` / ``b`` (``american``,
        ``decimal``, ``implied_probability``), ``favourite``,
        ``fair_probability_a`` and ``sources`` (how many sportsbooks backed it;
        book identities are never exposed). An unpriced bout returns ``None``
        blocks with ``points == 0``. Information only, not betting advice.
        """
        return self.get(f"fights/{fight_id}/odds")

    def fight_odds_history(
        self,
        fight_id: int,
        *,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every consensus point for one bout, oldest first (Pro plans and up).

        A point is stored only when the consensus moves, so the timestamps
        follow the market, not our refresh cadence. ``from_date`` /
        ``to_date`` are inclusive ``YYYY-MM-DD``. Below Pro the API answers
        403 ``tier_required`` (raised as :class:`FightAPIError`).
        """
        return self._paginate(
            f"fights/{fight_id}/odds/history",
            {"from": from_date, "to": to_date},
            limit,
        )

    def fight_stats(self, fight_id: int) -> List[Dict[str, Any]]:
        """Per-fight totals for both corners."""
        return self.get(f"fights/{fight_id}/stats")

    def fight_rounds(self, fight_id: int) -> List[Dict[str, Any]]:
        """Round-by-round stat lines for both corners."""
        return self.get(f"fights/{fight_id}/rounds")

    def fight_scorecards(self, fight_id: int) -> Dict[str, Any]:
        """The judges' scorecards for a bout — the official commission record.

        Returns the decision type, any point deductions, and one card per
        judge with their score for every round, their totals, and
        ``winner_fighter_id`` (who *that* judge gave it to). Scores are
        oriented to ``fighter_a_id``/``fighter_b_id``, both repeated on the
        payload.

        Check ``scores_known`` on a card before charting totals: when it is
        false the commission published only the outcome, so the totals are a
        1-0 / 1-1 / 0-0 placeholder and ``rounds`` is empty. Raises
        :class:`APIError` (404) for a bout that did not go to the judges.
        """
        return self.get(f"fights/{fight_id}/scorecards")

    # --------------------------------------------------------------- judges

    def find_fights(
        self,
        org: Optional[str] = None,
        *,
        title_only: Optional[bool] = None,
        method: Optional[str] = None,
        division: Optional[str] = None,
        fighter: Optional[str] = None,
        winner: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        main_events_only: Optional[bool] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Completed bouts, filtered — newest first unless ``order="oldest"``.

        At least one narrowing filter is required (``title_only``, ``method``
        — ko / sub / dec / finish —, ``division``, ``fighter``, ``winner``,
        ``from_date``, ``to_date``, ``main_events_only``). The server serves
        25 rows a page and at most 10 pages. Each row is the bout plus its
        ``event`` (id, slug, title, org, starts_at).
        """
        return self._paginate(
            "fights/search",
            {
                "org": org,
                "title_only": _bool_param(title_only),
                "method": method,
                "division": division,
                "fighter": None if fighter is None else str(fighter),
                "winner": None if winner is None else str(winner),
                "from": from_date,
                "to": to_date,
                "main_events_only": _bool_param(main_events_only),
                "order": order,
            },
            limit,
        )

    def judges(
        self,
        q: Optional[str] = None,
        *,
        org: Optional[str] = None,
        min_fights: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every official who has scored a launch-org bout, busiest first.

        Each row carries career shape: fights, rounds scored, rounds scored
        10-8 or wider, three-judge cards that came back split, and
        ``lone_dissents`` — cards where this judge alone picked the other
        corner. Rates mean little below ~10 fights; pass ``min_fights=10``.
        """
        return self._paginate(
            "judges", {"q": q, "org": org, "min_fights": min_fights}, limit
        )

    def judge(self, judge_id: int) -> Dict[str, Any]:
        """One official's career aggregates."""
        return self.get(f"judges/{judge_id}")

    def split_decisions(
        self,
        org: Optional[str] = None,
        *,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Split and majority decisions, newest first, with every judge's card
        and the dissenting judges named. Commission records only."""
        return self._paginate(
            "scorecards/splits", {"org": org, "from": from_date, "to": to_date}, limit
        )

    def judge_scorecards(
        self, judge_id: int, *, limit: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Every card this judge has turned in, newest first.

        Each entry is the bout, its event, the decision type and this judge's
        own card, with ``lone_dissent`` / ``split`` flags and the
        ``colleagues``' totals. For the full round-by-round panel on one bout
        use :meth:`fight_scorecards`.
        """
        return self._paginate(f"judges/{judge_id}/scorecards", {}, limit)

    # -------------------------------------------------------------- fighters

    def fighters(
        self,
        q: Optional[str] = None,
        *,
        org: Optional[str] = None,
        country: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        return self._paginate("fighters", {"q": q, "org": org, "country": country}, limit)

    def fighter(self, id_or_slug: str, *, include: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Bio, ``records`` (career + per-org W-L-D keyed ``pro_mma`` / ``ufc`` / …),
        ``stats`` (one per-minute panel with a ``basis`` naming the bouts it
        covers), raw ``career_stats`` rows, Power Index, CC-licensed images,
        ``next_fight`` and ``last_fight``. ``include=["bonuses"]`` adds the UFC
        bonus ledger; ``include=["credentials"]`` adds grappling and wrestling
        pedigree, gyms and coaches (every row with ``sources`` and a
        ``confidence`` grade)."""
        return self.get(f"fighters/{id_or_slug}", include=",".join(include) if include else None)

    def fighter_history(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Complete multi-promotion career timeline."""
        return self.get(f"fighters/{id_or_slug}/history")

    def fighter_stats(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Raw career stat rows per scope (``pro-mma``, ``ufc-only`` …). For the
        readable split use ``fighter()["records"]`` / ``fighter()["stats"]``."""
        return self.get(f"fighters/{id_or_slug}/stats")

    def fighter_rankings(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Every ranking row the fighter ever held, newest first, across every
        board (``board`` is ``official`` / ``meta``; ``is_champion`` when rank 0).
        The endpoint is cursor-paginated since 2026-09-24 — this walks every
        page so the list is complete (a long career is 900+ rows)."""
        return list(self._paginate(f"fighters/{id_or_slug}/rankings", {}, None))

    def fighter_power_index(self, id_or_slug: str) -> Any:
        return self.get(f"fighters/{id_or_slug}/power-index")

    def compare(self, a: str, b: str) -> Dict[str, Any]:
        """Two fighters side by side (slugs or ids): bios with age, career
        stats, strike mix, win streaks, ``head_to_head``, ``common_opponents``,
        the ``booked_bout`` between them, the UFCalendar model ``prediction``
        for it (UFC; not betting advice) and ``power_index`` ratings."""
        return self.get("compare", a=a, b=b)

    # -------------------------------------------------------------- rankings

    def rankings(self, org: str = "ufc", *, date: Optional[str] = None, board: Optional[str] = None) -> Dict[str, Any]:
        """Official board, point-in-time. ``date="YYYY-MM-DD"`` returns the board
        valid on that day (UFC history back to 2013; rank 0 = champion)."""
        return self.get(f"rankings/{org}", date=date, board=board)

    def division_rankings(self, org: str, division: str, *, date: Optional[str] = None) -> Dict[str, Any]:
        return self.get(f"rankings/{org}/{division}", date=date)

    def champions(self) -> Any:
        """Current champions across every launch org."""
        return self.get("champions")

    def power_index(
        self,
        org: str = "ufc",
        *,
        view: Optional[str] = None,
        division: Optional[str] = None,
        days: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """UFCalendar Power Index board. ``view="movers"`` = biggest risers over
        ``days`` (default 365), ``view="peaks"`` = all-time peak ratings;
        ``division`` (e.g. ``"lightweight"``) narrows any view."""
        return self.get(f"power-index/{org}", view=view, division=division, days=days, limit=limit)

    # ------------------------------------------------------------ matchmaker

    def matchmaker(
        self, org: str = "ufc", *, division: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """UFCalendar's matchmaker: the fights worth making in one MMA promotion,
        scored 0-100, across the roster or for one ``division``
        (``last_meta["divisions"]`` lists the valid ones). Not a list of
        bookings; computed without the site's Fight DNA factor."""
        return self.get(f"matchmaker/{org}", division=division, limit=limit)

    def whos_next(self, fighter: str, *, limit: Optional[int] = None) -> Dict[str, Any]:
        """Who one fighter (slug or id) should fight next: the best-scored
        opponents with the Power Index win probability for each, plus the
        bout already booked (``booked_next``)."""
        return self.get(f"matchmaker/next/{fighter}", limit=limit)

    # ---------------------------------------------------------------- stats

    def leaderboard(
        self,
        org: str,
        metric: str,
        *,
        division: Optional[str] = None,
        country: Optional[str] = None,
        population: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """One Record Book leaderboard for one promotion (``metric`` e.g.
        ``"wins"``, ``"fastest_knockout"``, ``"finish_rate"``). Narrow with
        ``division`` (slug), ``country`` (ISO-2) or ``population="active"`` —
        not ``country`` and ``active`` together. ``last_meta["metric"]`` names
        the unit and what ``value_secondary`` means."""
        return self.get(
            "stats/leaders",
            org=org, metric=metric, division=division, country=country,
            population=population, limit=limit,
        )

    def record_book(
        self,
        org: str,
        *,
        division: Optional[str] = None,
        country: Optional[str] = None,
        population: Optional[str] = None,
        scope: Optional[str] = None,
        top: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Every leaderboard's top rows (``top``, default 10, max 25) for one
        promotion, grouped by category: ``[{category, boards: [{metric, rows}]}]``.
        ``scope`` = ``career`` · ``single_fight`` · ``round`` · ``division`` · ``event``."""
        return self.get(
            "stats/record-book",
            org=org, division=division, country=country, population=population,
            scope=scope, top=top,
        )

    def year_stats(self, year: int, *, org: Optional[str] = None) -> Dict[str, Any]:
        """One calendar year in numbers for one promotion, or every covered
        promotion when ``org`` is omitted: events, title fights, finish methods,
        divisions, fastest finishes, upsets, Power Index climbers, busiest
        fighters, host countries and the most-used judges."""
        return self.get(f"stats/years/{year}", org=org)

    # ----------------------------------------------------------------- misc

    def predictions_upcoming(self, *, event: Optional[str] = None) -> Any:
        """Model win probabilities for upcoming UFC bouts; ``event`` narrows to one card."""
        return self.get("predictions/upcoming", event=event)

    def broadcast_rights(
        self, org: str = "ufc", *, country: Optional[str] = None, series: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Who airs the promotion, per ISO-2 country — the org-wide deals, or a
        UFC sub-series grid with ``series="dwcs"`` / ``"rtufc"``."""
        return self.get(f"broadcast-rights/{org}", country=country, series=series)

    def venues(
        self,
        q: Optional[str] = None,
        *,
        country: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Venues that hosted a covered promotion, alphabetical. ``q`` (2+
        characters) matches name or city; ``country`` is an ISO-2 code or an
        English country name."""
        return self._paginate("venues", {"q": q, "country": country}, limit)

    def venue(self, venue_id: int) -> Dict[str, Any]:
        return self.get(f"venues/{venue_id}")

    def venue_events(
        self,
        venue_id: int,
        *,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every covered event at one venue, newest first (``order="asc"`` reverses)."""
        return self._paginate(
            f"venues/{venue_id}/events",
            {"status": status, "from": from_date, "to": to_date, "order": order},
            limit,
        )

    def search(self, q: str) -> Any:
        return self.get("search", q=q)

    def articles(
        self,
        q: Optional[str] = None,
        *,
        tag: Optional[str] = None,
        locale: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """UFCalendar's own editorial archive, newest first. ``q`` (2+
        characters) matches title, summary or a tag; ``tag`` is exact;
        ``locale`` is one of the 13 site languages (English fallback)."""
        return self._paginate("articles", {"q": q, "tag": tag, "locale": locale}, limit)

    def article(self, slug: str, *, locale: Optional[str] = None) -> Dict[str, Any]:
        """One article: full Markdown ``body_md`` (client widgets removed),
        author, tags, ``published_at``; ``served_locale`` names
        the language delivered."""
        return self.get(f"articles/{slug}", locale=locale)

    def usage(self) -> Dict[str, Any]:
        """Your key's month-to-date quota usage."""
        return self.get("usage")

    def calendar_ics_url(self, org: str = "ufc") -> str:
        """Subscribable ICS feed URL for calendar apps (authenticates via ``?key=``)."""
        return f"{self.base_url}/calendar/{org}.ics?key={self.api_key}"

    # ------------------------------------------------------------- webhooks

    def webhook_endpoints(self) -> List[Dict[str, Any]]:
        return self.get("webhook-endpoints")

    def create_webhook_endpoint(self, url: str, events: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Register a signed webhook (Pro and up). ``events`` ⊆
        ``event.announced``, ``fight.result``, ``card.changed``, ``event.completed``,
        ``odds.moved`` (the consensus line on an upcoming bout moved 5+
        implied-probability points or the favourite flipped).
        The signing secret is returned ONCE in the response."""
        body: Dict[str, Any] = {"url": url}
        if events:
            body["events"] = list(events)
        return self._request("POST", "webhook-endpoints", json=body).get("data")

    def delete_webhook_endpoint(self, endpoint_id: int) -> None:
        self._request("DELETE", f"webhook-endpoints/{endpoint_id}")

    def rotate_webhook_secret(self, endpoint_id: int) -> Dict[str, Any]:
        return self._request("POST", f"webhook-endpoints/{endpoint_id}/rotate-secret").get("data")
