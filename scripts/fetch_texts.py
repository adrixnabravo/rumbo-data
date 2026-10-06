"""Download the full text of Metro Board motions and staff reports.

Used to track motion follow-through: motions say what they ask for and by when;
staff reports say "On <date>, the Board passed Motion <n> ... by Directors ...".

    python scripts/fetch_texts.py --since 2023-01-01

Writes data/texts/YYYY.jsonl, one record per matter:
  {"matter_id", "file", "type", "intro_date", "text"}
Motions keep their full text. Reports keep only paragraphs that mention a motion.
Re-runs skip matters already saved unless --refresh-days covers them.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_legistar import get, ROOT  # noqa: E402

REPORT_TYPES = {"Informational Report", "Oral Report / Presentation", "Board Correspondence", "Program",
                "Policy", "Plan", "Budget", "Project", "Contract", "Agreement", "Fare / Tariff / Service Change"}
MOTION_TYPE = "Motion / Motion Response"
TAG = re.compile(r"<[^>]+>")


def plain_text(matter_id):
    versions = get(f"matters/{matter_id}/versions") or []
    if not versions:
        return ""
    key = max(versions, key=lambda v: int(v.get("Value") or 0))["Key"]
    t = get(f"matters/{matter_id}/texts/{key}") or {}
    txt = t.get("MatterTextPlain") or TAG.sub(" ", t.get("MatterTextRtf") or "")
    return re.sub(r"[ \t\r\f\v]+", " ", txt).strip()


def motion_paragraphs(txt):
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", txt) if p.strip()]
    keep = [p for p in paras if re.search(r"\bmotion\b", p, re.I)]
    return "\n".join(keep)[:8000]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--refresh-days", type=int, default=45)
    a = ap.parse_args()
    refresh_after = (dt.date.today() - dt.timedelta(days=a.refresh_days)).isoformat()

    matters = []
    for f in sorted(glob.glob(os.path.join(ROOT, "matters", "*.csv"))):
        with open(f, newline="", encoding="utf-8") as fh:
            matters += [m for m in csv.DictReader(fh) if m["intro_date"] >= a.since]

    out_dir = os.path.join(ROOT, "texts")
    os.makedirs(out_dir, exist_ok=True)
    saved = {}
    for f in glob.glob(os.path.join(out_dir, "*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                saved[r["matter_id"]] = r

    todo = [m for m in matters if (m["type"] == MOTION_TYPE or m["type"] in REPORT_TYPES)
            and (m["matter_id"] not in saved or m["intro_date"] >= refresh_after)]
    print(f"{len(todo)} matters to fetch ({len(saved)} already saved)")
    for n, m in enumerate(todo, 1):
        try:
            txt = plain_text(m["matter_id"])
        except Exception as e:  # keep going; one bad record shouldn't stop the run
            print(f"  skip {m['file']}: {e}", file=sys.stderr)
            continue
        body = txt[:20000] if m["type"] == MOTION_TYPE else motion_paragraphs(txt)
        saved[m["matter_id"]] = {"matter_id": m["matter_id"], "file": m["file"], "type": m["type"],
                                 "intro_date": m["intro_date"], "text": body}
        if n % 50 == 0:
            print(f"  {n}/{len(todo)}")

    by_year = {}
    for r in saved.values():
        by_year.setdefault(r["intro_date"][:4], []).append(r)
    for year, rows in by_year.items():
        rows.sort(key=lambda r: (r["intro_date"], r["file"]))
        with open(os.path.join(out_dir, f"{year}.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("done")


if __name__ == "__main__":
    main()
