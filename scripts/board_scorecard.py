"""Attendance, missed votes, conflicts and split votes for the full Metro Board.

    python scripts/board_scorecard.py --since 2025-10-01 --until 2026-10-01

Writes analysis/scorecard_<since>_<until>.csv and analysis/split_votes.csv.

Method
- Only full Board of Directors meetings (regular and special), not committees.
- A "decision" is one agenda item vote. The consent calendar is approved in a
  single vote, so all consent items at a meeting count as ONE decision.
  Without this, arriving after the consent vote looks like missing 15-20 votes.
- "Missed" = recorded as Absent (or blank) on that decision.
- "Attended" = cast at least one non-absent vote at that meeting.
- "Conflict" = the member declared a conflict and did not vote.
"""

import argparse
import collections
import csv
import glob
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load(kind):
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", kind, "*.csv"))):
        with open(f, newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-10-01")
    ap.add_argument("--until", default="2026-10-01")
    a = ap.parse_args()

    items = {r["item_id"]: r for r in load("items")}
    votes = [v for v in load("votes") if v["body"].startswith("Board of Directors")]
    window = [v for v in votes if a.since <= v["event_date"] < a.until]

    decision = {}
    meetings = collections.defaultdict(lambda: collections.defaultdict(list))
    for v in window:
        it = items.get(v["item_id"], {})
        key = (v["event_id"], "consent") if it.get("consent") == "1" else (v["event_id"], v["item_id"])
        decision[(v["person"], key)] = v["vote"]
        meetings[v["person"]][v["event_id"]].append(v["vote"])

    per = collections.defaultdict(collections.Counter)
    for (person, _), vote in decision.items():
        per[person][vote] += 1

    out = []
    for person, c in per.items():
        n = sum(c.values())
        missed = c["Absent"] + c[""]
        ms = meetings[person]
        attended = sum(1 for vs in ms.values() if any(x not in ("Absent", "") for x in vs))
        out.append({"member": person, "meetings": len(ms), "meetings_attended": attended,
                    "decisions": n, "missed": missed, "missed_pct": round(100 * missed / n, 1),
                    "conflicts": c["Conflict"], "nay": c["Nay"], "abstain": c["Abstain"], "aye": c["Aye"]})
    out.sort(key=lambda r: -r["missed_pct"])

    os.makedirs(os.path.join(ROOT, "analysis"), exist_ok=True)
    path = os.path.join(ROOT, "analysis", f"scorecard_{a.since}_{a.until}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"wrote {path}")

    # Every full-board item since 2015 where anyone voted no.
    by_item = collections.defaultdict(list)
    for v in votes:
        by_item[v["item_id"]].append(v)
    split = []
    for iid, vs in by_item.items():
        nays = [x["person"] for x in vs if x["vote"] == "Nay"]
        if nays:
            it = items.get(iid, {})
            split.append({"date": vs[0]["event_date"], "file": vs[0]["matter_file"], "action": vs[0]["action"],
                          "aye": sum(x["vote"] == "Aye" for x in vs), "nay": len(nays), "voted_no": "; ".join(nays),
                          "title": (it.get("title") or "").replace("\n", " ")[:300]})
    split.sort(key=lambda r: r["date"], reverse=True)
    path = os.path.join(ROOT, "analysis", "split_votes.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(split[0].keys()))
        w.writeheader()
        w.writerows(split)
    print(f"wrote {path}: {len(split)} split items out of {len(by_item)} voted items")


if __name__ == "__main__":
    main()
