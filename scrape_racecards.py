#!/usr/bin/env python3
"""
Free racecard scraper for UK & Ireland.

Primary target: Sporting Life public pages (and similar free sources).
This is intentionally simple and robust rather than complete.
You will need to evolve the selectors as sites change.

Usage:
  python scrape_racecards.py --date today
  python scrape_racecards.py --date 2026-11-21
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def fetch_sporting_life_meetings(d: date) -> list:
    """
    Fetch the list of UK/IRE meetings for a given date from Sporting Life.
    Returns a list of dicts with course name and basic race info.
    This is a starting point – selectors will need maintenance.
    """
    url = f"https://www.sportinglife.com/racing/racecards/{d.isoformat()}"
    print(f"Fetching {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, "lxml")
    meetings = []

    # Sporting Life structure changes; this is a defensive parse
    # Look for meeting containers
    for meeting in soup.select("[data-test-id='meeting'], .meeting, .RacecardMeeting"):
        course_el = meeting.select_one("h2, .meeting-name, [data-test-id='meeting-name']")
        course = course_el.get_text(strip=True) if course_el else "Unknown"
        races = []
        for race in meeting.select("[data-test-id='race'], .race, .RacecardRace"):
            time_el = race.select_one(".time, [data-test-id='race-time']")
            name_el = race.select_one(".race-name, [data-test-id='race-name']")
            races.append({
                "time": time_el.get_text(strip=True) if time_el else "",
                "name": name_el.get_text(strip=True) if name_el else "",
                "runners": []   # filled later if we drill into individual cards
            })
        if races:
            meetings.append({"course": course, "races": races})

    if not meetings:
        # Fallback: just record that we tried
        print("No structured meetings found – site layout may have changed.")
        print("Saving raw HTML for inspection.")
        raw_path = DATA_DIR / f"raw-sportinglife-{d.isoformat()}.html"
        raw_path.write_text(r.text, encoding="utf-8")
        print(f"Raw HTML saved to {raw_path}")

    return meetings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today", help="today | tomorrow | YYYY-MM-DD")
    args = parser.parse_args()

    d = parse_date(args.date)
    print(f"Scraping racecards for {d.isoformat()}")

    meetings = fetch_sporting_life_meetings(d)

    out = {
        "date": d.isoformat(),
        "source": "sportinglife",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "meetings": meetings
    }

    out_path = DATA_DIR / f"racecards-{d.isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} ({len(meetings)} meetings)")

    if not meetings:
        print("\nNote: Free scraping is fragile. You may need to update selectors")
        print("or switch to a different public source / free API tier.")
        print("See README for alternatives.")


if __name__ == "__main__":
    main()
