#!/usr/bin/env python3
"""
UK & Ireland Racecard Scraper (Sporting Life)
Saves racecards-YYYY-MM-DD.json into the repo root.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

ROOT_DIR = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

UK_IRE = {"ENG", "IRE", "EIRE", "SCO", "WAL", "GB", "UK", "IE", "NI",
          "United Kingdom", "Ireland", "Northern Ireland", "England", "Scotland", "Wales"}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def extract_next_data(html: str) -> dict:
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


def parse_odds(odds_str) -> float:
    if not odds_str:
        return 0.0
    s = str(odds_str).strip().upper()
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
        return v if v > 1.0 else 0.0
    except ValueError:
        return 0.0


def find_rides(node):
    if isinstance(node, dict):
        if "rides" in node and isinstance(node["rides"], list) and node["rides"]:
            return node["rides"]
        for v in node.values():
            res = find_rides(v)
            if res:
                return res
    elif isinstance(node, list):
        for item in node:
            res = find_rides(item)
            if res:
                return res
    return None


def fetch_race_runners(date_str: str, course_name: str, race_id: str, race_name: str) -> list:
    """Fetch full runner list from the individual race page."""
    if not race_id:
        return []

    course_slug = slugify(course_name)
    race_slug = slugify(race_name)[:80] or "race"
    url = f"https://www.sportinglife.com/racing/racecards/{date_str}/{course_slug}/racecard/{race_id}/{race_slug}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            # fallback: try without the long slug
            url2 = f"https://www.sportinglife.com/racing/racecards/{date_str}/{course_slug}/racecard/{race_id}"
            r = requests.get(url2, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return []

        data = extract_next_data(r.text)
        rides = find_rides(data) or []
        runners = []

        for ride in rides:
            if str(ride.get("ride_status", "")).upper() in ("NON_RUNNER", "WITHDRAWN", "NR"):
                continue
            horse = ride.get("horse") or {}
            name = horse.get("name") or ride.get("horse_name")
            if not name:
                continue

            betting = ride.get("betting") or {}
            odds_str = (
                betting.get("current_odds")
                or betting.get("forecast_odds")
                or betting.get("decimal_odds")
                or ""
            )
            # also try bookmakerOdds list
            if not odds_str and isinstance(ride.get("bookmakerOdds"), list) and ride["bookmakerOdds"]:
                odds_str = ride["bookmakerOdds"][0].get("odds") or ride["bookmakerOdds"][0].get("decimal") or ""

            dec = parse_odds(odds_str)
            if dec <= 1.0:
                dec = 5.0  # fallback so bots still have something to work with

            form_figs = ""
            try:
                form_figs = str(horse.get("formsummary", {}).get("display_text", "") or "")
            except Exception:
                pass

            wins = form_figs.count("1")
            places = form_figs.count("2") + form_figs.count("3")
            form_score = min(0.9, 0.35 + wins * 0.15 + places * 0.07)

            jockey = ""
            if isinstance(ride.get("jockey"), dict):
                jockey = ride["jockey"].get("name", "")
            trainer = ""
            if isinstance(ride.get("trainer"), dict):
                trainer = ride["trainer"].get("name", "")

            runners.append({
                "name": name,
                "odds": dec,
                "jockey": jockey,
                "trainer": trainer,
                "form": form_figs,
                "form_score": round(form_score, 2),
                "trainer_score": round(min(0.85, 0.4 + wins * 0.1), 2),
                "pedigree_score": 0.5,
                "value_score": round(min(0.85, max(0.15, 1.0 / dec + 0.1)), 2),
            })
        return runners
    except Exception as e:
        print(f"  Runner fetch error ({race_id}): {e}", file=sys.stderr)
        return []


def fetch_meetings(d: date) -> list:
    date_str = d.isoformat()
    url = f"https://www.sportinglife.com/racing/racecards/{date_str}"
    print(f"Fetching {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return []

    next_data = extract_next_data(r.text)
    try:
        raw_meetings = next_data["props"]["pageProps"]["meetings"]
    except (KeyError, TypeError):
        print("Could not find meetings in page data", file=sys.stderr)
        return []

    meetings = []
    for m in raw_meetings:
        summary = m.get("meeting_summary") or {}
        course_info = summary.get("course") or {}
        country = (
            (course_info.get("country") or {}).get("short_name")
            or course_info.get("country_code")
            or ""
        )
        course_name = course_info.get("name") or summary.get("course_name") or "Unknown"

        if country and country.upper() not in UK_IRE:
            continue

        races = []
        for race in m.get("races") or []:
            ref = race.get("race_summary_reference") or {}
            race_id = str(ref.get("id") or race.get("id") or "")
            race_time = race.get("time") or race.get("off_time") or ""
            race_name = race.get("name") or ""
            race_class = race.get("race_class") or ""
            if race_class and f"Class {race_class}" not in race_name:
                race_name = f"{race_name} (Class {race_class})"

            print(f"  {course_name} {race_time} – fetching runners…")
            runners = fetch_race_runners(date_str, course_name, race_id, race_name)
            time.sleep(0.4)  # be polite

            races.append({
                "time": race_time,
                "name": race_name,
                "runners": runners,
                "race_id": race_id,
            })

        if races:
            meetings.append({
                "course": course_name,
                "going": summary.get("going") or "",
                "races": races,
            })

    return meetings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    d = parse_date(args.date)

    print(f"Scraping UK & IRE racecards for {d.isoformat()}")
    meetings = fetch_meetings(d)

    total_runners = sum(len(r["runners"]) for m in meetings for r in m["races"])
    print(f"Found {len(meetings)} meetings, {total_runners} total runners")

    out = {
        "date": d.isoformat(),
        "source": "sportinglife",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "meetings": meetings,
    }
    out_path = ROOT_DIR / f"racecards-{d.isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
