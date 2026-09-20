"""ufcalendar — Python client for the UFCalendar Fight API.

    from ufcalendar import FightAPI

    api = FightAPI("ufcalendar_...")            # or UFCAL_API_KEY env var
    for event in api.events(org="ufc"):          # upcoming UFC cards, soonest first
        print(event["starts_at"], event["title"])

    board = api.rankings("ufc", date="2016-11-14")   # rankings point-in-time since 2013
    print(board["snapshot_date"], board["divisions"][0]["entries"][0])

Docs: https://api.ufcalendar.com/docs · pricing + free 1-day trial:
https://www.ufcalendar.com/developers
"""

from .client import FightAPI, FightAPIError

__all__ = ["FightAPI", "FightAPIError"]
__version__ = "0.5.0"
