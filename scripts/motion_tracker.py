"""Track Metro Board motions from vote to follow-through.

    python scripts/motion_tracker.py --since 2023-01-01

For every motion the full board adopted, find:
  - who wrote it (the "Motion by ..." authors, first name = lead)
  - when it passed and its agenda item number at that meeting
  - whether it asked staff to report back, and by when
  - later staff reports that say they respond to it
    (they read: "On July 25, 2024, the Board passed Motion 48 ...")

Writes analysis/motion_tracker.csv. Statuses:
  Responded         a later staff report cites this motion
  Overdue           a report-back deadline passed and no citing report was found
  Waiting           a report-back deadline is still ahead
  No report found   it asked for a report back with no clear deadline, and none was found
  Direct action     it acted directly (approved, adopted, funded) and asked for no report

"No report found" and "Overdue" mean Rumbo's automated search found nothing.
A response may exist under a different name, as a memo, or as an oral update.
"""

import argparse
import collections
import csv
import datetime as dt
import glob
import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
WORDNUM = {"thirty": 30, "forty-five": 45, "sixty": 60, "ninety": 90, "one hundred twenty": 120,
           "one hundred and twenty": 120, "one hundred eighty": 180, "one hundred and eighty": 180, "six months": 180}


def load_csv(kind):
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", kind, "*.csv"))):
        with open(f, newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def load_texts():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "texts", "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                out[r["file"]] = r
    return out


AUTH = re.compile(r"Motion by\s+(?:Directors?\s+|Chair\s+|Vice Chair\s+)?(.+?)\s+(?:that|to direct|to)\b", re.I | re.S)


def authors(title):
    m = AUTH.search(re.sub(r"\s+", " ", title))
    if not m:
        return []
    names = re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1))
    return [n.strip().strip(".").split()[-1] for n in names if n.strip()]


def deadline(text, passed):
    t = re.sub(r"\s+", " ", text.lower())
    marks = [i for i in (t.find("therefore move"), t.find(" move that"), t.find("motion by")) if i >= 0]
    if marks:
        t = t[min(marks):]
    asks = bool(re.search(r"report back|return to the board|report to the board|provide (?:an? )?(?:update|report)|status report", t))
    days = []
    for m in re.finditer(r"(?:within|in)\s+(\d{2,3})\s+days", t):
        days.append(int(m.group(1)))
    for w, n in WORDNUM.items():
        if re.search(r"(?:within|in)\s+" + w + r"(?:\s*\(\d+\))?\s+days", t) or (w == "six months" and re.search(r"within six months", t)):
            days.append(n)
    dates = []
    for m in re.finditer(r"(?:in|by|at the|no later than)\s+(?:the\s+)?(" + "|".join(MONTHS) + r")\s+(20\d\d)", t):
        d = dt.date(int(m.group(2)), MONTHS.index(m.group(1)) + 1, 28)
        if d > passed:
            dates.append(d)
    due = None
    if days:
        due = passed + dt.timedelta(days=min(days))
    if dates:
        d = min(dates)
        due = min(due, d) if due else d
    recurring = bool(re.search(r"\bquarterly\b|every (?:three|six) months|\bannually\b|\bbi-?annual", t))
    return asks or bool(due), due, recurring


CITE = re.compile(r"(?:on|at its|at the|in)\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{1,2}),?)?\s+(20\d\d)[^.]{0,160}?\bmotion\s+(\d+(?:\.\d+)?)", re.I)
CITE2 = re.compile(r"\bmotion\s+(\d+(?:\.\d+)?)\b[^.]{0,160}?(" + "|".join(MONTHS) + r")(?:\s+(\d{1,2}),?)?\s+(20\d\d)", re.I)


def citations(text):
    out = set()
    for m in CITE.finditer(text):
        mon, day, yr, num = m.groups()
        out.add((num, int(yr), MONTHS.index(mon.lower()) + 1, int(day) if day else None))
    for m in CITE2.finditer(text):
        num, mon, day, yr = m.groups()
        out.add((num, int(yr), MONTHS.index(mon.lower()) + 1, int(day) if day else None))
    return out


UNDATED = re.compile(r"(?:response to|responding to|report back on|update on|subject:)\s+(?:board\s+)?motion\s+(\d+(?:\.\d+)?)", re.I)


def undated(text):
    return {m.group(1) for m in UNDATED.finditer(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today)

    matters = {m["file"]: m for m in load_csv("matters")}
    texts = load_texts()
    items = load_csv("items")

    # Where each motion was adopted by the full board, and its item number there.
    adopted = {}
    for it in items:
        m = matters.get(it["matter_file"])
        if not m or m["type"] != "Motion / Motion Response" or not it["body"].startswith("Board of Directors"):
            continue
        if "motion by" not in (m["title"] or "").lower():
            continue
        if not (it["action"] or "").upper().startswith(("APPROVED", "ADOPTED")):
            continue
        if it["event_date"] < a.since:
            continue
        prev = adopted.get(it["matter_file"])
        if not prev or it["event_date"] < prev["event_date"]:
            adopted[it["matter_file"]] = it

    # Index every citation in later reports: (item number, year, month) -> reports
    cites = collections.defaultdict(list)
    loose = collections.defaultdict(list)
    for f, r in texts.items():
        if r["type"] == "Motion / Motion Response" and "motion by" in r["text"][:400].lower():
            continue  # a motion citing another motion is not a response
        for num, yr, mon, day in citations(r["text"]):
            cites[(num, yr, mon)].append((r["intro_date"], f, day))
        for num in undated(r["text"]):
            loose[num].append((r["intro_date"], f))

    rows = []
    for f, it in sorted(adopted.items(), key=lambda kv: kv[1]["event_date"], reverse=True):
        m = matters[f]
        passed = dt.date.fromisoformat(it["event_date"])
        num = (it["agenda_number"] or "").strip()
        text = texts.get(f, {}).get("text") or m["title"]
        asks, due, recurring = deadline(text, passed)
        hits = sorted({(d, rf) for d, rf, day in cites.get((num, passed.year, passed.month), [])
                       if d >= it["event_date"] and (day is None or day == passed.day) and rf != f})
        if not hits and num:
            later = [o for o in adopted.values() if o["agenda_number"] == num and o["matter_file"] != f
                     and it["event_date"] < o["event_date"] <= (passed + dt.timedelta(days=548)).isoformat()]
            cutoff = min([o["event_date"] for o in later], default=(passed + dt.timedelta(days=548)).isoformat())
            hits = sorted({(d, rf) for d, rf in loose.get(num, []) if it["event_date"] <= d < cutoff and rf != f})
        if hits:
            status = "Responded"
        elif not asks:
            status = "Direct action"
        elif due and due < today:
            status = "Overdue"
        elif due:
            status = "Waiting"
        else:
            status = "No report found"
        au = authors(m["title"])
        rows.append({
            "file": f, "passed": it["event_date"], "item": num, "lead": au[0] if au else "",
            "coauthors": "; ".join(au[1:]), "asked_report": "yes" if asks else "no",
            "due": due.isoformat() if due else "", "recurring": "yes" if recurring else "no",
            "days_overdue": (today - due).days if status == "Overdue" else "",
            "status": status, "responses": "; ".join(f"{rf} ({d})" for d, rf in hits),
            "first_response_days": (dt.date.fromisoformat(hits[0][0]) - passed).days if hits else "",
            "title": re.sub(r"\s+", " ", m["title"])[:400],
        })

    # Hand-checked corrections, documented in analysis/motion_overrides.csv
    ov_path = os.path.join(ROOT, "analysis", "motion_overrides.csv")
    if os.path.exists(ov_path):
        with open(ov_path, newline="", encoding="utf-8") as fh:
            ov = {o["file"]: o for o in csv.DictReader(fh)}
        for r in rows:
            o = ov.get(r["file"])
            if o:
                r["status"], r["responses"], r["days_overdue"] = o["status"], o["responses"], ""
                r["note"] = o["note"]
                d = re.search(r"\((\d{4}-\d{2}-\d{2})\)", o["responses"])
                if d:
                    r["first_response_days"] = (dt.date.fromisoformat(d.group(1)) - dt.date.fromisoformat(r["passed"])).days
    for r in rows:
        r.setdefault("note", "")

    os.makedirs(os.path.join(ROOT, "analysis"), exist_ok=True)
    path = os.path.join(ROOT, "analysis", "motion_tracker.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}: {len(rows)} motions")
    print(collections.Counter(r["status"] for r in rows))


if __name__ == "__main__":
    main()
