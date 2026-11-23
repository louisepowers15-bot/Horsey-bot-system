#!/usr/bin/env python3
"""
UK & Ireland Racecard Scraper (Sporting Life)
Saves racecards-YYYY-MM-DD.json with going, distance, runners.
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

UK_IRE = {
    "ENG", "IRE", "EIRE", "SCO", "WAL", "WALE", "GB", "UK", "IE", "NI",
    "United Kingdom", "Ireland", "Northern Ireland", "England", "Scotland", "Wales",
    # Sporting Life sometimes truncates country short_name (e.g. "Wale" for Wales)
    "Wale",
}

def is_uk_ire_country(country) -> bool:
    """Accept UK/Ireland meetings even when country codes are truncated/odd."""
    if country is None:
        return True  # unknown → keep (better than dropping Bangor etc.)
    if isinstance(country, dict):
        short = str(country.get("short_name") or country.get("code") or "").strip()
        long = str(country.get("long_name") or country.get("name") or "").strip()
    else:
        short = str(country).strip()
        long = ""
    if not short and not long:
        return True
    u_short = short.upper()
    u_long = long.upper()
    if short in UK_IRE or long in UK_IRE:
        return True
    if u_short in {x.upper() for x in UK_IRE}:
        return True
    # prefix / contains for truncations: Wale→Wales, Scot→Scotland
    for token in ("ENG", "IRE", "SCOT", "WAL", "WALE", "GB", "UK", "NI", "EIRE"):
        if u_short.startswith(token) or token.startswith(u_short[:3]) and len(u_short) >= 3:
            return True
    for token in ("ENGLAND", "IRELAND", "SCOTLAND", "WALES", "BRITAIN"):
        if token in u_long or token in u_short:
            return True
    return False



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



def detect_race_code(race_name: str, distance: str = "", course: str = "") -> str:
    """
    Classify race as flat | hurdle | chase | nh_flat | unknown from title text.
    Free-card heuristic only — based on race name wording.
    """
    n = f"{race_name or ''} {distance or ''}".lower()
    # Order matters: chase before hurdle (some titles mention both rarely)
    if re.search(r"chase|steeplechase|beginners'? chase|novice(?:s)? chase", n):
        return "chase"
    if re.search(r"hurdle|hurdles|novice(?:s)? hurdle|maiden hurdle", n):
        return "hurdle"
    if re.search(r"n\.?h\.?\s*flat|bumper|national hunt flat", n):
        return "nh_flat"
    if re.search(r"flat|handicap|maiden|stakes|nursery|listed|group", n):
        # Handicap/maiden alone are ambiguous (can be jumps), so require non-jumps context
        if re.search(r"(hurdle|chase|bumper)", n):
            pass
        elif re.search(r"(flat|nursery|group\s*[123]|listed|sprint)", n):
            return "flat"
    # Course-level hint: known AW flat tracks often flat when not jumps meeting
    # Leave unknown if unclear rather than guess wrong
    if re.search(r"(handicap|maiden|stakes)", n) and not re.search(r"(hurdle|chase|bumper)", n):
        # Many UK winter "handicap" on AW are flat; on turf winter often jumps — leave unknown if mixed
        return "unknown"
    return "unknown"


def detect_surface(course: str, going: str) -> str:
    """turf | AW | unknown"""
    g = (going or "").lower()
    c = (course or "").lower().strip()
    aw_courses = {
        "newcastle", "wolverhampton", "lingfield", "chelmsford", "chelmsford city",
        "southwell", "kempton", "dundalk",
    }
    if any(x in g for x in ("standard", "polytrack", "tapeta", "fibresand", "dirt", "all weather", "all-weather")):
        return "AW"
    if c in aw_courses:
        if g and any(x in g for x in ("good", "soft", "firm", "heavy", "yielding")) and "standard" not in g:
            return "turf"
        return "AW"
    if g:
        return "turf"
    return "unknown"


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


def find_first(node, keys):
    """Find first value for any of keys in nested structure."""
    if isinstance(node, dict):
        for k in keys:
            if k in node and node[k] not in (None, "", []):
                return node[k]
        for v in node.values():
            found = find_first(v, keys)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node[:5]:
            found = find_first(item, keys)
            if found is not None:
                return found
    return None



def weight_to_lbs(w) -> float | None:
    """Parse '11-4' or '9-9' stone-lbs into total pounds."""
    if w is None:
        return None
    s = str(w).strip()
    if not s:
        return None
    if "-" in s:
        try:
            st, lb = s.split("-", 1)
            return int(st) * 14 + int(lb)
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def summarise_previous_results(horse_obj: dict, limit: int = 6) -> list[dict]:
    """Compact previous runs for weight/surface/code analysis."""
    prev = horse_obj.get("previous_results") or []
    out = []
    for p in prev[:limit]:
        if not isinstance(p, dict):
            continue
        out.append({
            "date": p.get("date") or "",
            "course": p.get("course_name") or p.get("course_shortcode") or "",
            "distance": str(p.get("distance") or ""),
            "weight": p.get("weight") or "",
            "weight_lbs": weight_to_lbs(p.get("weight")),
            "position": p.get("position"),
            "going": p.get("going") or p.get("going_shortcode") or "",
            "run_type": str(p.get("run_type") or ""),
            "race_name": str(p.get("race_name") or "")[:80],
            "odds": p.get("odds"),
        })
    return out



def _position_char(pos, casualty="") -> str:
    cas = str(casualty or "").upper()
    if cas in ("F", "FELL", "FALL", "FEL"):
        return "F"
    if cas in ("P", "PU", "PULLED UP", "PULLED_UP"):
        return "P"
    if cas in ("U", "UR", "UNSEATED", "UNSEATED RIDER"):
        return "U"
    if cas in ("R", "REF", "REFUSED"):
        return "R"
    if cas in ("B", "BD", "BROUGHT DOWN"):
        return "B"
    if pos is None or pos == "":
        return ""
    try:
        pi = int(pos)
        if pi <= 0:
            return "0"
        if pi >= 10:
            return "0"
        return str(pi)
    except Exception:
        s = str(pos).strip().upper()
        if s[:1] in "1234567890FPURB":
            return s[:1]
        return ""


def form_from_previous_results(previous_results: list, limit: int = 8) -> str:
    """Most-recent-first form string from structured previous_results only."""
    chars = []
    for p in (previous_results or [])[:limit]:
        if not isinstance(p, dict):
            continue
        ch = _position_char(p.get("position"), p.get("casualty"))
        if ch:
            chars.append(ch)
    return "".join(chars)


def fetch_race_detail(date_str, course_name, race_id, race_name):
    """Return (runners, distance, going_override). Form always prefers previous_results."""
    if not race_id:
        return [], "", ""
    course_slug = slugify(course_name)
    race_slug = slugify(race_name)[:80] or "race"
    urls = [
        f"https://www.sportinglife.com/racing/racecards/{date_str}/{course_slug}/racecard/{race_id}/{race_slug}",
        f"https://www.sportinglife.com/racing/racecards/{date_str}/{course_slug}/racecard/{race_id}",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            data = extract_next_data(r.text)
            rides = find_rides(data) or []
            if not rides:
                continue
            distance = str(find_first(data, ["distance", "distance_text", "race_distance"]) or "")
            going = str(find_first(data, ["going", "going_text"]) or "")

            runners = []
            for ride in rides:
                if str(ride.get("ride_status", "")).upper() in ("NON_RUNNER", "WITHDRAWN", "NR"):
                    continue
                horse = ride.get("horse") or {}
                if not isinstance(horse, dict):
                    horse = {}
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
                if not odds_str and isinstance(ride.get("bookmakerOdds"), list) and ride["bookmakerOdds"]:
                    odds_str = ride["bookmakerOdds"][0].get("odds") or ride["bookmakerOdds"][0].get("decimal") or ""

                dec = parse_odds(odds_str)
                if dec <= 1.0:
                    dec = 8.0

                # --- form: ALWAYS prefer previous_results over formsummary ---
                prev_raw = horse.get("previous_results") or []
                if not isinstance(prev_raw, list):
                    prev_raw = []
                form_figs = form_from_previous_results(prev_raw, limit=8)
                form_summary = ""
                try:
                    form_summary = str((horse.get("formsummary") or {}).get("display_text") or "")
                except Exception:
                    form_summary = ""
                if not form_figs and form_summary:
                    # last resort only — mark as summary-sourced
                    form_figs = form_summary.replace(" ", "")
                form_source = "previous_results" if form_from_previous_results(prev_raw) else (
                    "formsummary" if form_summary else "none"
                )

                wins = form_figs.count("1")
                places = form_figs.count("2") + form_figs.count("3")
                form_score = min(0.9, 0.35 + wins * 0.12 + places * 0.06)
                if form_figs[:1] == "1":
                    form_score = min(0.9, form_score + 0.05)
                elif form_figs[:1] in ("0", "5", "6", "7", "8", "9", "F", "P", "U", "R", "B"):
                    form_score = max(0.15, form_score - 0.08)

                jockey = ""
                if isinstance(ride.get("jockey"), dict):
                    jockey = ride.get("jockey", {}).get("name", "") or ""
                trainer = ""
                if isinstance(ride.get("trainer"), dict):
                    trainer = ride.get("trainer", {}).get("name", "") or ""
                combo = 0.55 if (jockey and trainer) else 0.45

                weight_raw = ride.get("handicap") or ride.get("weight") or ""
                if isinstance(weight_raw, dict):
                    weight_raw = weight_raw.get("display") or weight_raw.get("value") or ""
                weight_raw = str(weight_raw).strip()
                weight_lbs = weight_to_lbs(weight_raw)

                prev = summarise_previous_results(horse, limit=8)
                win_weights = [
                    p["weight_lbs"] for p in prev
                    if p.get("position") in (1, "1", 1.0) and p.get("weight_lbs")
                ]
                last_win_weight_lbs = win_weights[0] if win_weights else None
                weight_delta = None
                if weight_lbs is not None and last_win_weight_lbs is not None:
                    weight_delta = round(weight_lbs - last_win_weight_lbs, 1)

                runners.append({
                    "name": name,
                    "odds": dec,
                    "jockey": jockey,
                    "trainer": trainer,
                    "form": form_figs,
                    "form_source": form_source,
                    "form_summary_raw": form_summary,  # kept for debug only
                    "form_score": round(form_score, 2),
                    "trainer_score": round(min(0.85, 0.4 + wins * 0.08), 2),
                    "jockey_score": round(combo, 2),
                    "pedigree_score": 0.5,
                    "value_score": round(min(0.85, max(0.15, 1.0 / dec + 0.1)), 2),
                    "weight": weight_raw,
                    "weight_lbs": weight_lbs,
                    "last_win_weight_lbs": last_win_weight_lbs,
                    "weight_delta_lbs": weight_delta,
                    "previous_results": prev,
                })
            if runners:
                return runners, distance, going
        except Exception as e:
            print(f"  detail error {race_id}: {e}", file=sys.stderr)
    return [], "", ""



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
        # Also pass full country object when available for robust matching
        country_obj = course_info.get("country")
        if country_obj:
            if not is_uk_ire_country(country_obj):
                continue
        elif country and not is_uk_ire_country(country):
            continue

        meeting_going = summary.get("going") or ""
        races = []
        for race in m.get("races") or []:
            ref = race.get("race_summary_reference") or {}
            race_id = str(ref.get("id") or race.get("id") or "")
            race_time = race.get("time") or race.get("off_time") or ""
            race_name = race.get("name") or ""
            race_class = race.get("race_class") or ""
            if race_class and f"Class {race_class}" not in race_name:
                race_name = f"{race_name} (Class {race_class})"
            # distance sometimes on list page
            list_distance = str(race.get("distance") or race.get("distance_text") or "")

            print(f"  {course_name} {race_time} – fetching…")
            runners, dist, going_ov = fetch_race_detail(date_str, course_name, race_id, race_name)
            time.sleep(0.35)

            dist_final = dist or list_distance or ""
            going_final = going_ov or meeting_going or ""
            races.append({
                "time": race_time,
                "name": race_name,
                "distance": dist_final,
                "going": going_final,
                "surface": detect_surface(course_name, going_final),
                "code": detect_race_code(race_name, dist_final, course_name),
                "runners": runners,
                "race_id": race_id,
            })

        if races:
            meetings.append({
                "course": course_name,
                "going": meeting_going,
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
    total = sum(len(r["runners"]) for m in meetings for r in m["races"])
    print(f"Found {len(meetings)} meetings, {total} runners")

    # Fingerprint race ids — helps detect "tomorrow" pages that still show today's card
    race_ids = []
    for m in meetings:
        for r in m.get("races") or []:
            if r.get("race_id"):
                race_ids.append(str(r["race_id"]))
    race_ids = sorted(set(race_ids))

    # Compare to yesterday file if present
    yday = (d - timedelta(days=1)).isoformat()
    ypath = ROOT_DIR / f"racecards-{yday}.json"
    note = None
    if ypath.exists() and race_ids:
        try:
            ydata = json.loads(ypath.read_text(encoding="utf-8"))
            y_ids = sorted({
                str(r.get("race_id"))
                for m in ydata.get("meetings") or []
                for r in m.get("races") or []
                if r.get("race_id")
            })
            if y_ids and y_ids == race_ids:
                note = (
                    f"WARNING: race ids for {d.isoformat()} are identical to {yday}. "
                    "Sporting Life may not have published the next day's card yet — "
                    "this file may still be the previous day's meetings."
                )
                print(note)
        except Exception:
            pass

    out = {
        "date": d.isoformat(),
        "source": "sportinglife",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "race_id_fingerprint": race_ids[:40],
        "note": note,
        "meetings": meetings,
    }
    path = ROOT_DIR / f"racecards-{d.isoformat()}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
