#!/usr/bin/env python3
"""Scrape UK/IRE race results from Sporting Life for a date."""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
UK_IRE = {"ENG", "IRE", "EIRE", "SCO", "WAL", "GB", "UK", "IE", "NI", "England", "Ireland", "Scotland", "Wales"}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "yesterday":
        return date.today() - timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def extract_next(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def parse_odds(s) -> float:
    if not s:
        return 0.0
    s = str(s).strip().upper()
    if s in ("EVS", "EVENS"):
        return 2.0
    if "/" in s:
        try:
            n, d = s.split("/")
            return round(float(n) / float(d) + 1.0, 2)
        except ValueError:
            return 0.0
    try:
        v = float(s)
        return v if v > 1 else 0.0
    except ValueError:
        return 0.0


def find_rides(node):
    if isinstance(node, dict):
        if "rides" in node and isinstance(node["rides"], list) and node["rides"]:
            return node["rides"]
        for v in node.values():
            found = find_rides(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_rides(item)
            if found:
                return found
    return None


def fetch_race_result(date_str, course, race_id, race_name):
    course_slug = slugify(course)
    race_slug = slugify(race_name)[:90] or "race"
    url = f"https://www.sportinglife.com/racing/results/{date_str}/{course_slug}/{race_id}/{race_slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            url2 = f"https://www.sportinglife.com/racing/results/{date_str}/{course_slug}/{race_id}"
            r = requests.get(url2, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return []
        data = extract_next(r.text)
        rides = find_rides(data) or []
        out = []
        for ride in rides:
            horse = ride.get("horse") or {}
            name = horse.get("name") or ride.get("horse_name")
            if not name:
                continue
            pos = ride.get("finish_position")
            try:
                pos = int(pos) if pos is not None else None
            except (TypeError, ValueError):
                pos = None
            status = str(ride.get("ride_status") or ride.get("status") or "").upper()
            # Normalise common non-runner flags from Sporting Life
            if not status or status in ("NONE", "NULL"):
                # Some payloads put NR in position text / horse status
                hs = str((ride.get("horse") or {}).get("status") or "").upper()
                if hs:
                    status = hs
            if any(x in status for x in ("NON_RUNNER", "NON-RUNNER", "WITHDRAWN")) or status in ("NR", "WD"):
                status = "NON_RUNNER"
                pos = 0
            sp = ""
            betting = ride.get("betting") or {}
            sp = betting.get("starting_price") or betting.get("current_odds") or ""
            out.append({
                "name": name,
                "position": pos,
                "status": status,
                "sp": parse_odds(sp) or None,
            })
        return out
    except Exception as e:
        print(f"  result fetch fail {course} {race_id}: {e}", file=sys.stderr)
        return []


def fetch_results(d: date) -> dict:
    date_str = d.isoformat()
    url = f"https://www.sportinglife.com/racing/results/{date_str}"
    print(f"Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    data = extract_next(r.text)
    try:
        raw = data["props"]["pageProps"]["meetings"]
    except (KeyError, TypeError):
        print("No meetings in results page", file=sys.stderr)
        return {"date": date_str, "meetings": []}

    meetings = []
    for m in raw:
        summary = m.get("meeting_summary") or {}
        course_info = summary.get("course") or {}
        country = (course_info.get("country") or {}).get("short_name") or course_info.get("country_code") or ""
        course = course_info.get("name") or summary.get("course_name") or "Unknown"
        if country and country.upper() not in UK_IRE:
            # also allow by course list page country field on race
            pass
        races_out = []
        for race in m.get("races") or []:
            stage = str(race.get("race_stage") or "").upper()
            if stage and stage not in ("WEIGHEDIN", "RESULT", "FINISHED", "OFF"):
                # still try if top_horses present
                if not race.get("top_horses"):
                    continue
            country_r = (race.get("country_short_name") or country or "").upper()
            if country_r and country_r not in UK_IRE and country_r not in ("",):
                continue
            course_r = race.get("course_name") or course
            ref = race.get("race_summary_reference") or {}
            race_id = str(ref.get("id") or "")
            race_name = race.get("name") or ""
            race_time = race.get("time") or race.get("off_time") or ""
            runners = []
            if race_id:
                print(f"  {course_r} {race_time} …")
                runners = fetch_race_result(date_str, course_r, race_id, race_name)
                time.sleep(0.3)
            if not runners and race.get("top_horses"):
                for th in race["top_horses"]:
                    runners.append({
                        "name": th.get("name"),
                        "position": th.get("position"),
                        "status": "FINISHED",
                        "sp": parse_odds(th.get("odds")) or None,
                    })
            if runners:
                races_out.append({
                    "time": race_time,
                    "name": race_name,
                    "course": course_r,
                    "distance": race.get("distance") or "",
                    "going": race.get("going") or summary.get("going") or "",
                    "field_size": len(runners),
                    "runners": runners,
                })
        if races_out:
            meetings.append({"course": course, "races": races_out})
    return {
        "date": date_str,
        "source": "sportinglife",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "meetings": meetings,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="yesterday")
    args = p.parse_args()
    d = parse_date(args.date)
    data = fetch_results(d)
    n = sum(len(r["runners"]) for m in data["meetings"] for r in m["races"])
    path = ROOT / f"results-{d.isoformat()}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {path} meetings={len(data['meetings'])} runners={n}")


if __name__ == "__main__":
    main()
