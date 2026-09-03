"""Thin, dependency-light client for https://api.ufcalendar.com/v1.

Every method returns the parsed ``data`` value of the JSON envelope
(``{"data": ..., "meta": ...}``); list endpoints are generators that follow
cursor pagination for you. Errors raise :class:`FightAPIError` carrying the
API's ``code``, ``message`` and ``request_id`` (quote the request id when
you write to api@ufcalendar.com).

The API serves no betting odds, by design. Fighter ``images`` are Wikimedia
Commons / Creative Commons files — the ``license`` and ``artist`` fields you
receive must be displayed as a credit.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional, Sequence

import requests

DEFAULT_BASE_URL = "https://api.ufcalendar.com/v1"
_TIMEOUT = 30


class FightAPIError(Exception):
    """An error response from the Fight API."""

    def __init__(self, status: int, code: str, message: str, request_id: Optional[str] = None):
        super().__init__(f"{status} {code}: {message}" + (f" (request_id={request_id})" if request_id else ""))
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id


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
                "User-Agent": "ufcalendar-python/0.1.0",
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
            return {}
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                raise FightAPIError(resp.status_code, str(err.get("code", "error")), str(err.get("message", resp.text[:200])), err.get("request_id"))
            raise FightAPIError(resp.status_code, "http_error", resp.text[:200], resp.headers.get("x-request-id"))
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

    # ------------------------------------------------------------------ orgs

    def orgs(self) -> List[Dict[str, Any]]:
        """Launch orgs with capability flags (stats / rounds / rankings / broadcasts / predictions)."""
        return self.get("orgs")

    def org(self, slug: str) -> Dict[str, Any]:
        return self.get(f"orgs/{slug}")

    # ---------------------------------------------------------------- events

    def events(
        self,
        org: Optional[str] = None,
        *,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Schedule + results. Bare call = upcoming calendar, soonest first.

        ``status="completed"`` (or ``order="desc"``) browses the archive newest-first.
        ``from_date`` / ``to_date`` are ``YYYY-MM-DD``.
        """
        return self._paginate(
            "events",
            {"org": org, "status": status, "from": from_date, "to": to_date, "order": order},
            limit,
        )

    def event(self, id_or_slug: str) -> Dict[str, Any]:
        """One event with its full fight card, venue and broadcasts."""
        return self.get(f"events/{id_or_slug}")

    def event_changes(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Card-change diff log (fight added/removed, opponent swapped, date moved)."""
        return self.get(f"events/{id_or_slug}/changes")

    # ---------------------------------------------------------------- fights

    def fight(self, fight_id: int) -> Dict[str, Any]:
        return self.get(f"fights/{fight_id}")

    def fight_stats(self, fight_id: int) -> List[Dict[str, Any]]:
        """Per-fight totals for both corners."""
        return self.get(f"fights/{fight_id}/stats")

    def fight_rounds(self, fight_id: int) -> List[Dict[str, Any]]:
        """Round-by-round stat lines for both corners."""
        return self.get(f"fights/{fight_id}/rounds")

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

    def fighter(self, id_or_slug: str) -> Dict[str, Any]:
        """Bio, records, career stats, Power Index and CC-licensed images."""
        return self.get(f"fighters/{id_or_slug}")

    def fighter_history(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Complete multi-promotion career timeline."""
        return self.get(f"fighters/{id_or_slug}/history")

    def fighter_stats(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Career statistics per scope (``pro-mma``, ``ufc-only`` …)."""
        return self.get(f"fighters/{id_or_slug}/stats")

    def fighter_rankings(self, id_or_slug: str) -> List[Dict[str, Any]]:
        """Every official ranking row the fighter ever held, newest first."""
        return self.get(f"fighters/{id_or_slug}/rankings")

    def fighter_power_index(self, id_or_slug: str) -> Any:
        return self.get(f"fighters/{id_or_slug}/power-index")

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

    def power_index(self, org: str = "ufc") -> Any:
        return self.get(f"power-index/{org}")

    # ----------------------------------------------------------------- misc

    def predictions_upcoming(self) -> Any:
        """Model win probabilities for upcoming UFC bouts."""
        return self.get("predictions/upcoming")

    def broadcast_rights(self, org: str = "ufc", *, country: Optional[str] = None) -> List[Dict[str, Any]]:
        """Who airs the promotion, per ISO-2 country."""
        return self.get(f"broadcast-rights/{org}", country=country)

    def venue(self, venue_id: int) -> Dict[str, Any]:
        return self.get(f"venues/{venue_id}")

    def search(self, q: str) -> Any:
        return self.get("search", q=q)

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
        ``event.announced``, ``fight.result``, ``card.changed``, ``event.completed``.
        The signing secret is returned ONCE in the response."""
        body: Dict[str, Any] = {"url": url}
        if events:
            body["events"] = list(events)
        return self._request("POST", "webhook-endpoints", json=body).get("data")

    def delete_webhook_endpoint(self, endpoint_id: int) -> None:
        self._request("DELETE", f"webhook-endpoints/{endpoint_id}")

    def rotate_webhook_secret(self, endpoint_id: int) -> Dict[str, Any]:
        return self._request("POST", f"webhook-endpoints/{endpoint_id}/rotate-secret").get("data")
