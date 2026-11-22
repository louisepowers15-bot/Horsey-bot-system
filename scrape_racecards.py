#!/usr/bin/env python3
"""
UK & Ireland Racecard Scraper (Sporting Life __NEXT_DATA__ JSON Extractor)
Saves racecards-YYYY-MM-DD.json directly into the repo root folder.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

# Save directly in the repository root so GitHub Pages can read it
ROOT_DIR = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

UK_IRE_COUNTRIES = {"ENG", "IRE", "EIRE", "SCO", "WAL", "GB", "UK", "IE", "United Kingdom", "Ireland", "Northern Ireland", "NI"}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def extract_next_data(html: str) -> dict:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def parse_fractional_to_decimal(odds_str: str) -> float:
    if not odds_str:
        return 5.0
    odds_str = str(odds_str).strip().upper()
    if odds_str in ("EVS", "EVENS"):
        return 2.0
    if "/" in odds_str:
        try:
            num, den = odds_str.split("/")
            return round((float(num) / float(den)) + 1.0, 2)
        except ValueError:
            return 5.0
    try:
        val = float(odds_str)
        return val if val > 1.0 else 5.0
    except ValueError:
        return 5.0


def find_meetings_recursive(obj, found=None):
    if found is None:
        found = []
    if isinstance(obj, dict):
        # Sporting Life meeting objects typically have 'meeting_summary' and 'races'
        if "meeting_summary" in obj and "races" in obj and isinstance(obj["races"], list):
            found.append(obj)
        else:
            for v in obj.values():
                find_meetings_recursive(v, found)
    elif isinstance(obj, list):
        for item in obj:
            find_meetings_recursive(item, found)
    return found


def fetch_race_runners(race_id: str) -> list:
    """Fetch individual racecard JSON for full runner list and live odds."""
    url = f"https://sportinglife.com{race_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = extract_next_data(r.text)
        runners = []

        def find_rides(node):
            if isinstance(node, dict):
                if "rides" in node and isinstance(node["rides"], list):
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

        rides = find_rides(data) or []
        for ride in rides:
            if ride.get("ride_status") == "NON_RUNNER":
                continue
            horse = ride.get("horse", {})
            name = horse.get("name") or ride.get("horse_name")
            if not name:
                continue

            # Extract betting odds if available
            betting = ride.get("betting", {})
            odds_str = betting.get("current_odds") or betting.get("forecast_odds") or ""
            dec_odds = parse_fractional_to_decimal(odds_str)

            # Simple form score heuristic from recent finishing positions
            form_figs = str(horse.get("formsummary", {}).get("display_text", ""))
            wins = form_figs.count("1")
            places = form_figs.count("2") + form_figs.count("3")
            form_score = min(0.9, 0.35 + (wins * 0.15) + (places * 0.07))

            runners.append({
                "name": name,
                "odds": dec_odds,
                "jockey": ride.get("jockey", {}).get("name", ""),
                "trainer": ride.get("trainer", {}).get("name", ""),
                "form": form_figs,
                "form_score": round(form_score, 2),
                "trainer_score": round(min(0.85, 0.4 + (wins * 0.1)), 2),
                "pedigree_score": 0.5,
                "value_score": round(min(0.85, dec_odds / 15.0), 2),
            })
        return runners
    except Exception:
        return []


def fetch_sporting_life_meetings(d: date) -> list:
    url = f"https://www.sportinglife.com/racing/racecards/{d.isoformat()}"
    print(f"Fetching {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return []

    next_data = extract_next_data(r.text)
    raw_meetings = find_meetings_recursive(next_data)
    meetings = []

    for m in raw_meetings:
        summary = m.get("meeting_summary", {})
        course_info = summary.get("course", {})
        country = course_info.get("country", {}).get("short_name", "") or course_info.get("country_code", "")
        course_name = course_info.get("name") or summary.get("course_name") or "Unknown"

        # Keep UK & Ireland meetings only
        if country and country.upper() not in UK_IRE_COUNTRIES:
            continue

        races = []
        for race in m.get("races", []):
            race_id = str(race.get("race_summary_reference", {}).get("id") or race.get("id") or "")
            race_time = race.get("time", "")
            race_name = race.get("name", "")
            race_class = race.get("race_class", "")
            if race_class and f"Class {race_class}" not in race_name:
                race_name = f"{race_name} (Class {race_class})"

            runners = fetch_race_runners(race_id) if race_id else []
            races.append({
                "time": race_time,
                "name": race_name,
                "runners": runners
            })

        if races:
            meetings.append({
                "course": course_name,
                "going": summary.get("going", ""),
                "races": races
            })

    return meetings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today", help="today | tomorrow | YYYY-MM-DD")
    args = parser.parse_args()

    d = parse_date(args.date)
    print(f"Scraping UK & IRE racecards for {d.isoformat()}")
    meetings = fetch_sporting_life_meetings(d)

    out = {
        "date": d.isoformat(),
        "source": "sportinglife",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "meetings": meetings
    }

    out_path = ROOT_DIR / f"racecards-{d.isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} ({len(meetings)} meetings)")


if __name__ == "__main__":
    main()

