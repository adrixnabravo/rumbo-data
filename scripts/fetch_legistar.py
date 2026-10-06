"""Download LA Metro Board records from the public Legistar Web API.

Writes plain CSV files under data/ so anyone can check Rumbo's numbers.

Usage:
    python scripts/fetch_legistar.py --since 2026-01-01           # one window
    python scripts/fetch_legistar.py --since 2015-01-01 --until 2016-01-01
    python scripts/fetch_legistar.py --days 120                    # nightly refresh

Each run rewrites the per-year files for every year it touches, so a
re-run is always safe. Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://webapi.legistar.com/v1/metro"
PAGE = 1000
PAUSE = 0.15  # seconds between calls, to be polite to the API
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# Bodies whose meetings are not real public meetings.
SKIP_BODY_WORDS = ("Test", "(SAP)")


# ---------------------------------------------------------------- HTTP

def get(path: str, params: dict | None = None, tries: int = 5):
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "rumbo-data (public records research)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            time.sleep(PAUSE)
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/{tries} in {wait}s: {url} ({e})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {tries} tries: {url}")


def get_all(path: str, params: dict | None = None):
    params = dict(params or {})
    out, skip = [], 0
    while True:
        params.update({"$top": PAGE, "$skip": skip})
        batch = get(path, params)
        out.extend(batch)
        if len(batch) < PAGE:
            return out
        skip += PAGE


def odate(d: dt.date) -> str:
    return f"datetime'{d.isoformat()}'"


def day(v):
    return (v or "")[:10]


# ---------------------------------------------------------------- CSV

def write_csv(path: str, rows: list[dict], fields: list[str]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted(rows, key=lambda r: tuple(str(r.get(f, "")) for f in fields[:3]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


EVENT_F = ["event_id", "date", "time", "body_id", "body", "agenda_status", "minutes_status", "location", "agenda_url", "minutes_url", "video_url"]
ITEM_F = ["event_id", "event_date", "body", "item_id", "agenda_number", "agenda_sequence", "matter_id", "matter_file", "matter_type", "action", "passed", "mover", "seconder", "roll_call_flag", "consent", "title"]
VOTE_F = ["event_id", "event_date", "body", "item_id", "agenda_number", "matter_file", "action", "person_id", "person", "vote", "vote_result"]
ROLL_F = ["event_id", "event_date", "body", "item_id", "person_id", "person", "status"]
MATTER_F = ["matter_id", "file", "type", "status", "body", "intro_date", "agenda_date", "passed_date", "requester", "name", "title"]


# ---------------------------------------------------------------- pulls

def pull_reference():
    persons = get_all("persons")
    write_csv(os.path.join(ROOT, "persons.csv"),
              [{"person_id": p["PersonId"], "name": p["PersonFullName"], "first": p.get("PersonFirstName"),
                "last": p.get("PersonLastName"), "active": p.get("PersonActiveFlag")} for p in persons],
              ["person_id", "name", "first", "last", "active"])
    bodies = get_all("bodies")
    write_csv(os.path.join(ROOT, "bodies.csv"),
              [{"body_id": b["BodyId"], "name": b["BodyName"], "type": b.get("BodyTypeName"),
                "active": b.get("BodyActiveFlag"), "members": b.get("BodyNumberOfMembers")} for b in bodies],
              ["body_id", "name", "type", "active", "members"])
    records = get_all("officerecords")
    write_csv(os.path.join(ROOT, "memberships.csv"),
              [{"person_id": r.get("OfficeRecordPersonId"), "person": r.get("OfficeRecordFullName"),
                "body_id": r.get("OfficeRecordBodyId"), "body": r.get("OfficeRecordBodyName"),
                "title": r.get("OfficeRecordTitle"), "member_type": r.get("OfficeRecordMemberType"),
                "start": day(r.get("OfficeRecordStartDate")), "end": day(r.get("OfficeRecordEndDate"))} for r in records],
              ["person_id", "person", "body_id", "body", "title", "member_type", "start", "end"])
    print(f"reference: {len(persons)} persons, {len(bodies)} bodies, {len(records)} memberships")


def pull_events(start: dt.date, end: dt.date):
    """Pull events in [start, end) with their items, votes and roll calls."""
    events = get_all("events", {"$filter": f"EventDate ge {odate(start)} and EventDate lt {odate(end)}",
                                "$orderby": "EventDate"})
    events = [e for e in events if not any(w in (e.get("EventBodyName") or "") for w in SKIP_BODY_WORDS)]
    print(f"events {start}..{end}: {len(events)}")

    by_year = defaultdict(lambda: {"events": [], "items": [], "votes": [], "rolls": []})
    for n, e in enumerate(events, 1):
        eid, edate, body = e["EventId"], day(e["EventDate"]), e.get("EventBodyName")
        y = by_year[edate[:4]]
        y["events"].append({"event_id": eid, "date": edate, "time": e.get("EventTime"), "body_id": e.get("EventBodyId"),
                            "body": body, "agenda_status": e.get("EventAgendaStatusName"),
                            "minutes_status": e.get("EventMinutesStatusName"), "location": e.get("EventLocation"),
                            "agenda_url": e.get("EventAgendaFile"), "minutes_url": e.get("EventMinutesFile"),
                            "video_url": e.get("EventVideoPath")})
        items = get(f"events/{eid}/eventitems", {"AgendaNote": 1, "MinutesNote": 1})
        for it in items:
            iid = it["EventItemId"]
            action = it.get("EventItemActionName")
            row = {"event_id": eid, "event_date": edate, "body": body, "item_id": iid,
                   "agenda_number": (it.get("EventItemAgendaNumber") or "").strip().rstrip("."),
                   "agenda_sequence": it.get("EventItemAgendaSequence"),
                   "matter_id": it.get("EventItemMatterId"), "matter_file": it.get("EventItemMatterFile"),
                   "matter_type": it.get("EventItemMatterType"), "action": action,
                   "passed": it.get("EventItemPassedFlagName"), "mover": it.get("EventItemMover"),
                   "seconder": it.get("EventItemSeconder"), "roll_call_flag": it.get("EventItemRollCallFlag"),
                   "consent": it.get("EventItemConsent"), "title": (it.get("EventItemTitle") or "")[:500]}
            y["items"].append(row)
            if action or it.get("EventItemPassedFlagName"):
                for v in get(f"eventitems/{iid}/votes"):
                    y["votes"].append({"event_id": eid, "event_date": edate, "body": body, "item_id": iid,
                                       "agenda_number": row["agenda_number"], "matter_file": row["matter_file"],
                                       "action": action, "person_id": v.get("VotePersonId"),
                                       "person": v.get("VotePersonName"), "vote": v.get("VoteValueName"),
                                       "vote_result": v.get("VoteResult")})
            if it.get("EventItemRollCallFlag"):
                for rc in get(f"eventitems/{iid}/rollcalls"):
                    y["rolls"].append({"event_id": eid, "event_date": edate, "body": body, "item_id": iid,
                                       "person_id": rc.get("RollCallPersonId"), "person": rc.get("RollCallPersonName"),
                                       "status": rc.get("RollCallValueName")})
        if n % 10 == 0:
            print(f"  {n}/{len(events)} events")

    for year, y in by_year.items():
        merge_year("events", year, y["events"], EVENT_F, "event_id", start, end, "date")
        merge_year("items", year, y["items"], ITEM_F, "item_id", start, end, "event_date")
        merge_year("votes", year, y["votes"], VOTE_F, None, start, end, "event_date")
        merge_year("rollcalls", year, y["rolls"], ROLL_F, None, start, end, "event_date")


def merge_year(kind, year, new_rows, fields, key, start, end, date_field):
    """Replace rows inside [start, end) and keep rows outside the window."""
    path = os.path.join(ROOT, kind, f"{year}.csv")
    kept = [r for r in read_csv(path) if not (start.isoformat() <= r[date_field] < end.isoformat())]
    write_csv(path, kept + new_rows, fields)
    print(f"  wrote {kind}/{year}.csv ({len(kept) + len(new_rows)} rows)")


def pull_matters(start: dt.date, end: dt.date):
    rows = get_all("matters", {"$filter": f"MatterIntroDate ge {odate(start)} and MatterIntroDate lt {odate(end)}",
                               "$orderby": "MatterIntroDate"})
    by_year = defaultdict(list)
    for m in rows:
        intro = day(m.get("MatterIntroDate"))
        by_year[intro[:4] or "unknown"].append({
            "matter_id": m["MatterId"], "file": m.get("MatterFile"), "type": m.get("MatterTypeName"),
            "status": m.get("MatterStatusName"), "body": m.get("MatterBodyName"), "intro_date": intro,
            "agenda_date": day(m.get("MatterAgendaDate")), "passed_date": day(m.get("MatterPassedDate")),
            "requester": m.get("MatterRequester"), "name": m.get("MatterName"),
            "title": (m.get("MatterTitle") or "")[:1000]})
    for year, ys in by_year.items():
        merge_year("matters", year, ys, MATTER_F, "matter_id", start, end, "intro_date")
    print(f"matters {start}..{end}: {len(rows)}")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD, inclusive")
    ap.add_argument("--until", help="YYYY-MM-DD, exclusive (default: 60 days from today)")
    ap.add_argument("--days", type=int, help="refresh the last N days")
    ap.add_argument("--skip-reference", action="store_true")
    a = ap.parse_args()

    today = dt.date.today()
    end = dt.date.fromisoformat(a.until) if a.until else today + dt.timedelta(days=60)
    if a.days:
        start = today - dt.timedelta(days=a.days)
    elif a.since:
        start = dt.date.fromisoformat(a.since)
    else:
        start = today - dt.timedelta(days=120)

    if not a.skip_reference:
        pull_reference()
    # Work year by year so a long backfill writes progress as it goes.
    cur = start
    while cur < end:
        nxt = min(dt.date(cur.year + 1, 1, 1), end)
        pull_matters(cur, nxt)
        pull_events(cur, nxt)
        cur = nxt

    with open(os.path.join(ROOT, "last_updated.json"), "w") as f:
        json.dump({"updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "window": [start.isoformat(), end.isoformat()], "source": API}, f, indent=2)


if __name__ == "__main__":
    main()
