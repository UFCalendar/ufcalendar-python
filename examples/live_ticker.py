"""Live fight-night ticker over the UFCalendar live WebSocket (Pro plans and up).

    pip install 'ufcalendar[live]'
    UFCAL_API_KEY=ufcalendar_... python live_ticker.py ufc-331

Prints one line per change, e.g.

    R2 3:41 · Oliveira 41 vs Makhachev 37 sig. strikes

Docs: https://api.ufcalendar.com/docs · keys: https://www.ufcalendar.com/account/api
"""

import sys

from ufcalendar import FightAPI


def clock(sec):
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def line(state):
    cur = (state or {}).get("current")
    if not cur:
        return None
    by_src = {row.get("src_id"): row for row in (state.get("card") or [])}
    bout = by_src.get(cur.get("src_id")) or {}
    a, b = bout.get("a") or {}, bout.get("b") or {}
    stats = cur.get("stats") or {}
    sa = (stats.get("a") or {}).get("sig_strikes_landed")
    sb = (stats.get("b") or {}).get("sig_strikes_landed")
    where = f"R{cur.get('round') or '?'} {clock(cur.get('clock_sec'))}"
    names = f"{a.get('short') or a.get('name') or 'A'} {sa if sa is not None else '-'} vs {b.get('short') or b.get('name') or 'B'} {sb if sb is not None else '-'}"
    return f"{where} · {names} sig. strikes"


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "ufc-331"
    api = FightAPI()  # reads UFCAL_API_KEY
    last = None
    for frame in api.live_stream(slug):
        kind = frame.get("type")
        if kind == "error":
            print("error:", frame.get("code"), frame.get("message"), file=sys.stderr)
            return 1
        state = frame.get("data")
        if state is None:
            print(f"{slug}: nothing streaming yet — waiting…")
            continue
        text = line(state)
        if text and text != last:
            last = text
            print(text, flush=True)
        if kind == "fight.final":
            res = state.get("last") or {}
            print(f"  FINAL · {res.get('method')} R{res.get('round')} {res.get('time')}", flush=True)
        if kind == "event.completed":
            print("card over")
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
