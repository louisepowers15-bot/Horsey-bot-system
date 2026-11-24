#!/usr/bin/env python3
"""
Free multi-bot tips with human tipster-style reasons.

Uses everything available on a free Sporting Life card:
  form string, trainer, jockey, odds/rank, field size, going, distance,
  surface (turf vs AW), and day-level trainer/jockey books built from the
  full card (how busy the yard/jockey is today).

Reasons vary by bot and by what data actually exists — no filler about
empty form, and no identical sentences across bots.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent

try:
    from history_store import load_index, lookup, horse_history_bits
    HAS_HISTORY = True
except Exception:
    HAS_HISTORY = False
    def load_index():
        return {"runs": 0}
    def lookup(table, *parts, default=0.12):
        return default, 0
    def horse_history_bits(*a, **k):
        return []

BOT_NAMES = [
    "BloodlineBetty",
    "DevilAdvocate",
    "FormFox",
    "HotTrainer",
    "PaceProphet",
    "ValueHunter",
]

WEIGHTS = {
    "FormFox":        {"form": 0.30, "trend": 0.10, "trainer": 0.10, "jockey": 0.08, "combo": 0.08, "value": 0.10, "field": 0.06, "going": 0.08, "trip": 0.10},
    "HotTrainer":     {"form": 0.14, "trend": 0.06, "trainer": 0.24, "jockey": 0.12, "combo": 0.16, "value": 0.08, "field": 0.05, "going": 0.07, "trip": 0.08},
    "ValueHunter":    {"form": 0.16, "trend": 0.08, "trainer": 0.10, "jockey": 0.08, "combo": 0.08, "value": 0.28, "field": 0.08, "going": 0.07, "trip": 0.07},
    "DevilAdvocate":  {"form": 0.20, "trend": 0.08, "trainer": 0.10, "jockey": 0.10, "combo": 0.10, "value": 0.18, "field": 0.08, "going": 0.08, "trip": 0.08},
    "BloodlineBetty": {"form": 0.16, "trend": 0.12, "trainer": 0.12, "jockey": 0.08, "combo": 0.10, "value": 0.10, "field": 0.06, "going": 0.12, "trip": 0.14},
    "PaceProphet":    {"form": 0.16, "trend": 0.08, "trainer": 0.10, "jockey": 0.14, "combo": 0.12, "value": 0.10, "field": 0.14, "going": 0.08, "trip": 0.08},
}

# Common UK/IRE all-weather tracks
AW_COURSES = {
    "newcastle", "wolverhampton", "lingfield", "chelmsford", "chelmsford city",
    "southwell", "kempton", "dundalk",
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def parse_form_tokens(form: str):
    if not form:
        return []
    s = str(form).strip().upper().replace("-", " ").replace("/", " ")
    return re.findall(r"[1-9]|0|F|P|U|R|B|C|S", s)[:8]


def form_metrics(form: str):
    tokens = parse_form_tokens(form)
    if not tokens:
        return 0.38, 0.48
    score = 0.30
    for i, t in enumerate(tokens[:6]):
        w = 1.0 - i * 0.1
        if t == "1":
            score += 0.12 * w
        elif t == "2":
            score += 0.08 * w
        elif t == "3":
            score += 0.05 * w
        elif t in ("4", "5"):
            score += 0.025 * w
        elif t in ("F", "P", "U", "R", "B"):
            score -= 0.07 * w
        elif t == "0":
            score -= 0.025 * w
    score = max(0.15, min(0.9, score))

    def half(chunk):
        if not chunk:
            return 0.45
        sc = 0.38
        for t in chunk:
            if t == "1":
                sc += 0.1
            elif t in ("2", "3"):
                sc += 0.05
            elif t in ("F", "P", "U"):
                sc -= 0.07
        return max(0.2, min(0.85, sc))

    trend = max(0.2, min(0.85, 0.5 + (half(tokens[:3]) - half(tokens[3:6])) * 0.75))
    return score, trend


def distance_furlongs(dist: str) -> float | None:
    if not dist:
        return None
    d = dist.lower().replace("½", ".5").replace("¼", ".25").replace("¾", ".75")
    miles = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:ile)?s?\b", d)
    if m:
        miles += float(m.group(1))
    f = re.search(r"(\d+(?:\.\d+)?)\s*f", d)
    if f:
        miles += float(f.group(1)) / 8.0
    y = re.search(r"(\d+)\s*y", d)
    if y and not m and not f:
        miles = float(y.group(1)) / 1760.0
    if miles <= 0:
        return None
    return miles * 8.0  # furlongs


def trip_label(dist: str) -> str:
    f = distance_furlongs(dist)
    if f is None:
        return (dist or "").strip()
    if f < 6.5:
        return f"sprint ({dist.strip()})"
    if f < 9.5:
        return f"mile trip ({dist.strip()})"
    if f < 12.5:
        return f"middle distance ({dist.strip()})"
    if f < 16:
        return f"staying trip ({dist.strip()})"
    return f"marathon trip ({dist.strip()})"



def race_code_from_name(race_name: str) -> str:
    n = (race_name or "").lower()
    if re.search(r"\bchase\b|\bsteeplechase\b", n):
        return "chase"
    if re.search(r"\bhurdle\b|\bhurdles\b", n):
        return "hurdle"
    if re.search(r"\bbumper\b|\bn\.?h\.?\s*flat\b|\bnational hunt flat\b", n):
        return "nh_flat"
    if re.search(r"\b(nursery|group\s*[123]|listed stake)\b", n):
        return "flat"
    return "unknown"


def surface_from(course: str, going: str) -> str:
    g = (going or "").lower()
    c = (course or "").lower().strip()
    if any(x in g for x in ("standard", "polytrack", "tapeta", "fibresand", "dirt", "all weather", "all-weather")):
        return "AW"
    if c in AW_COURSES:
        # Kempton/Lingfield can be turf jumps; prefer going when present
        if g and any(x in g for x in ("good", "soft", "firm", "heavy", "yielding", "yielding")):
            if "standard" not in g:
                return "turf"
        return "AW"
    if g:
        return "turf"
    return "unknown"


def going_family(going: str) -> str:
    g = (going or "").lower()
    if not g:
        return ""
    if "heavy" in g or "soft" in g or "yielding" in g:
        return "softish"
    if "firm" in g or "hard" in g:
        return "quick"
    if "standard" in g or "poly" in g or "tapeta" in g:
        return "AW"
    if "good" in g:
        return "good"
    return g[:20]


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def build_day_books(flat_races: list[dict]) -> dict:
    """Aggregate today's card: trainer/jockey volume and mean odds."""
    trainers = defaultdict(lambda: {"n": 0, "odds": [], "courses": set()})
    jockeys = defaultdict(lambda: {"n": 0, "odds": [], "courses": set()})
    combos = defaultdict(lambda: {"n": 0, "odds": []})

    for race in flat_races:
        course = race.get("course") or ""
        for r in race.get("runners") or []:
            t = norm_name(r.get("trainer") or "")
            j = norm_name(r.get("jockey") or "")
            try:
                o = float(r.get("odds") or 0) or 0
            except Exception:
                o = 0
            if t:
                trainers[t]["n"] += 1
                if o:
                    trainers[t]["odds"].append(o)
                trainers[t]["courses"].add(course)
            if j:
                jockeys[j]["n"] += 1
                if o:
                    jockeys[j]["odds"].append(o)
                jockeys[j]["courses"].add(course)
            if t and j:
                combos[(j, t)]["n"] += 1
                if o:
                    combos[(j, t)]["odds"].append(o)

    def pack(d):
        out = {}
        for k, v in d.items():
            odds = v["odds"]
            out[k] = {
                "n": v["n"],
                "avg_odds": round(sum(odds) / len(odds), 2) if odds else None,
                "courses": len(v.get("courses") or []),
            }
        return out

    return {
        "trainers": pack(trainers),
        "jockeys": pack(jockeys),
        "combos": {
            f"{j}|{t}": {"n": v["n"], "avg_odds": round(sum(v["odds"]) / len(v["odds"]), 2) if v["odds"] else None}
            for (j, t), v in combos.items()
        },
    }


def enrich(runner, field_size, all_odds, going, distance, course, day_books):
    r = dict(runner)
    odds = max(1.15, float(r.get("odds") or 10.0))
    r["odds"] = odds
    form = str(r.get("form") or "").strip()
    fscore, trend = form_metrics(form)
    if r.get("form_score"):
        try:
            fscore = max(fscore, float(r["form_score"]) * 0.75)
        except Exception:
            pass
    r["_form"] = fscore
    r["_trend"] = trend
    r["_form_raw"] = form

    # Weight (today vs last win when available)
    r["_weight"] = str(r.get("weight") or "").strip()
    try:
        r["_weight_lbs"] = float(r["weight_lbs"]) if r.get("weight_lbs") is not None else None
    except Exception:
        r["_weight_lbs"] = None
    try:
        r["_last_win_weight_lbs"] = float(r["last_win_weight_lbs"]) if r.get("last_win_weight_lbs") is not None else None
    except Exception:
        r["_last_win_weight_lbs"] = None
    try:
        r["_weight_delta_lbs"] = float(r["weight_delta_lbs"]) if r.get("weight_delta_lbs") is not None else None
    except Exception:
        r["_weight_delta_lbs"] = None
    r["_previous_results"] = r.get("previous_results") or []
    r["_headgear"] = str(r.get("headgear") or "").strip()
    try:
        r["_days_off"] = int(r["days_off"]) if r.get("days_off") is not None else None
    except Exception:
        r["_days_off"] = None
    try:
        r["_age"] = int(r["age"]) if r.get("age") is not None else None
    except Exception:
        r["_age"] = None
    try:
        r["_or"] = int(r["official_rating"]) if r.get("official_rating") is not None else None
    except Exception:
        r["_or"] = None

    # Carrying more than last winning weight is a real negative, especially over longer trips
    delta = r["_weight_delta_lbs"]
    furlongs = r.get("_furlongs")  # may not be set yet

    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    tn, jn = norm_name(trainer), norm_name(jockey)

    # Base connection scores from card fields + day book strength
    t_base = float(r.get("trainer_score") or (0.52 if trainer else 0.4))
    j_base = float(r.get("jockey_score") or (0.52 if jockey else 0.4))
    t_day = day_books.get("trainers", {}).get(tn) or {}
    j_day = day_books.get("jockeys", {}).get(jn) or {}
    c_day = day_books.get("combos", {}).get(f"{jn}|{tn}") or {}

    # Busy credible books on the day nudge scores up slightly
    if t_day.get("n", 0) >= 3:
        t_base = min(0.82, t_base + 0.06)
    if j_day.get("n", 0) >= 3:
        j_base = min(0.82, j_base + 0.05)
    if c_day.get("n", 0) >= 2:
        combo = min(0.85, (t_base + j_base) / 2 + 0.12)
    else:
        combo = min(0.8, (t_base + j_base) / 2 + (0.06 if (trainer and jockey) else 0.0))

    r["_trainer"] = t_base
    r["_jockey"] = j_base
    r["_combo"] = combo
    r["_t_day_n"] = int(t_day.get("n") or 0)
    r["_j_day_n"] = int(j_day.get("n") or 0)
    r["_c_day_n"] = int(c_day.get("n") or 0)

    implied = 1.0 / odds
    edge = r["_form"] - implied
    r["_value"] = max(0.08, min(0.85, 0.42 + edge * 0.85))
    if odds >= 15:
        r["_value"] *= 0.55 if r["_form"] < 0.55 else 0.85
    if odds >= 25:
        r["_value"] *= 0.5 if r["_form"] < 0.6 else 0.75

    if field_size >= 11 and 4.5 <= odds <= 12:
        r["_field"] = 0.62
    elif field_size <= 4:
        r["_field"] = 0.58 if r["_form"] >= 0.5 else 0.34
    else:
        r["_field"] = 0.5

    surface = surface_from(course, going)
    gf = going_family(going)
    # Soft preference signals from surface match — free proxy only
    r["_surface"] = surface
    r["_code"] = "unknown"
    r["_going_family"] = gf
    r["_going"] = 0.56 if gf in ("good", "AW") else (0.53 if gf else 0.5)
    r["_trip"] = 0.54 if distance else 0.5
    r["_going_txt"] = going or ""
    r["_trip_txt"] = distance or ""
    r["_trip_label"] = trip_label(distance) if distance else ""
    r["_course"] = course or ""
    r["_furlongs"] = distance_furlongs(distance)

    # Apply weight penalty/bonus once we know trip length
    delta = r.get("_weight_delta_lbs")
    fur = r.get("_furlongs")
    if delta is not None:
        # +7lb over a staying trip hurts more than over a sprint
        scale = 0.012
        if fur and fur >= 16:
            scale = 0.02
        elif fur and fur >= 12:
            scale = 0.016
        elif fur and fur < 8:
            scale = 0.008
        # delta positive = carries more than last win
        r["_form"] = max(0.12, min(0.92, r["_form"] - delta * scale))
        if delta <= -3:
            r["_form"] = min(0.92, r["_form"] + 0.03)  # nice drop in weight

    # Past runs surface/code hints from previous_results on the card
    prev = r.get("_previous_results") or []
    aw_runs = sum(1 for p in prev if any(x in str(p.get("going") or "").lower() for x in ("st", "standard", "aw"))
                  or "aw" in str(p.get("course") or "").lower())
    turf_runs = sum(1 for p in prev if p.get("going") and not any(
        x in str(p.get("going") or "").lower() for x in ("st", "standard", "aw")))
    r["_prev_aw_runs"] = aw_runs
    r["_prev_turf_runs"] = turf_runs

    # Freshness / absence
    days = r.get("_days_off")
    if days is not None:
        if 14 <= days <= 45:
            r["_form"] = min(0.92, r["_form"] + 0.02)  # typical spacing
        elif days > 180:
            r["_form"] = max(0.12, r["_form"] - 0.06)  # long absence caution
        elif days > 100:
            r["_form"] = max(0.12, r["_form"] - 0.03)
        elif days < 7:
            r["_form"] = max(0.12, r["_form"] - 0.02)  # very quick reappearance

    # First-time headgear is information, not automatically good
    hg = (r.get("_headgear") or "").lower()
    if hg and any(x in hg for x in ("blinker", "hood", "visor", "tongue", "cheek")):
        r["_has_headgear"] = True
    else:
        r["_has_headgear"] = False

    sorted_odds = sorted(all_odds)
    try:
        r["_rank"] = sorted_odds.index(odds) + 1
    except ValueError:
        r["_rank"] = max(1, len(sorted_odds) // 2)
    return r


def score_bot(bot, r, rng):
    w = WEIGHTS[bot]
    s = (
        w["form"] * r["_form"]
        + w["trend"] * r["_trend"]
        + w["trainer"] * r["_trainer"]
        + w["jockey"] * r["_jockey"]
        + w["combo"] * r["_combo"]
        + w["value"] * r["_value"]
        + w["field"] * r["_field"]
        + w["going"] * r["_going"]
        + w["trip"] * r["_trip"]
    )
    if r["_rank"] <= 2 and r["_form"] >= 0.5:
        s += 0.045
    if r["_rank"] == 1 and r["_form"] >= 0.55:
        s += 0.03
    if r["odds"] >= 12 and r["_form"] < 0.52:
        s -= 0.12
    if r["odds"] >= 18 and r["_form"] < 0.58:
        s -= 0.18
    if r["odds"] >= 25:
        s -= 0.12
    if bot == "DevilAdvocate" and r["_rank"] == 1 and r["_form"] < 0.55:
        s -= 0.06
    if bot == "ValueHunter" and r["odds"] < 2.2:
        s -= 0.05
    # Surface specialists lean
    if bot in ("BloodlineBetty", "FormFox") and r.get("_surface") == "AW":
        s += 0.015
    s += rng.uniform(-0.025, 0.025)
    return max(0.08, min(0.93, s))


def choose_type(bot, r, field_size, prob):
    odds = r["odds"]
    if field_size < 5 or odds < 5.5:
        return "win"
    if r["_form"] < 0.45:
        return "win"
    if field_size >= 8 and odds >= 7.5 and prob >= 0.32 and r["_form"] >= 0.48:
        return "ew"
    return "win"


def pick_for_bot(bot, ranked, field_size):
    for prob, r in ranked:
        if r["odds"] >= 16 and r["_form"] < 0.55:
            continue
        if r["odds"] >= 20 and r["_rank"] >= 4 and r["_form"] < 0.6:
            continue
        tip_type = choose_type(bot, r, field_size, prob)
        return prob, r, tip_type
    market = [x for x in ranked if x[1]["_rank"] <= max(3, field_size // 2)]
    pool = market or ranked
    prob, r = pool[0]
    return prob, r, choose_type(bot, r, field_size, prob)






def _h(seed: str, *opts: str) -> str:
    opts = [o for o in opts if o]
    if not opts:
        return ""
    return opts[sum(ord(c) for c in seed) % len(opts)]


def _form_facts(form: str) -> list[str]:
    tokens = parse_form_tokens(form)
    if not tokens:
        return []
    facts = []
    last = tokens[0]
    last_map = {
        "1": "won last time",
        "2": "finished second last time",
        "3": "finished third last time",
        "0": "was out of the first three last time",
        "F": "fell last time",
        "P": "was pulled up last time",
        "U": "unseated last time",
        "R": "failed to complete last time",
        "B": "failed to complete last time",
    }
    if last in last_map:
        facts.append(last_map[last])
    wins = sum(1 for t in tokens[:6] if t == "1")
    places = sum(1 for t in tokens[:6] if t in ("1", "2", "3"))
    if wins >= 2:
        facts.append(f"has {wins} recent wins in the figures")
    elif places >= 3:
        facts.append(f"has been top-three {places} times recently")
    elif wins == 1:
        facts.append("has a win in the recent figures")
    return facts


def _wc(t: str) -> int:
    return len(t.split())


def tipster_reason(bot, r, tip_type, conf, field_size, rivals: list | None = None):
    """
    Human-sounding tip note built from ranked facts (card + history).
    Structure varies by bot and by which facts are strongest for this horse.
    """
    name = (r.get("name") or "This one").strip()
    odds = float(r.get("odds") or 10)
    form = (r.get("_form_raw") or r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    course = (r.get("_course") or "").strip()
    going = (r.get("_going_txt") or "").strip()
    trip = (r.get("_trip_txt") or "").strip()
    surface = r.get("_surface") or "unknown"
    code = (r.get("_code") or "unknown").lower()
    rank = int(r.get("_rank") or 0)
    form_s = float(r.get("_form") or 0.4)
    trend = float(r.get("_trend") or 0.5)
    t_day = int(r.get("_t_day_n") or 0)
    j_day = int(r.get("_j_day_n") or 0)
    hist_bits = list(r.get("_hist_bits") or [])
    hist_facts = list(r.get("_hist_facts") or [])  # richer structured lines
    weight = (r.get("_weight") or r.get("weight") or "").strip()
    wdelta = r.get("_weight_delta_lbs")
    days = r.get("_days_off")
    orating = r.get("_or")
    headgear = (r.get("_headgear") or "").strip()
    seed = f"{bot}|{name}|{course}|{rank}|{odds:.2f}|{tip_type}"
    ff = _form_facts(form)

    # --- rival snapshot ---
    fav = None
    if rivals:
        try:
            ordered = sorted(rivals, key=lambda x: float(x.get("odds") or 99))
            fav = ordered[0] if ordered else None
        except Exception:
            fav = None
    fav_name = (fav.get("name") or "").strip() if fav else ""
    fav_odds = float(fav.get("odds") or 0) if fav else 0
    fav_form = (fav.get("_form_raw") or fav.get("form") or "").strip() if fav else ""

    # --- score and collect candidate facts (text, weight) ---
    facts = []  # (priority, text)

    # History first when real samples exist
    for h in hist_facts[:4]:
        facts.append((90, h))
    for h in hist_bits[:3]:
        if h and h not in [f[1] for f in facts]:
            facts.append((85, h if h.endswith(".") else h + "."))

    # Form
    if ff:
        if form_s >= 0.62:
            facts.append((80, f"Form is solid: {ff[0]}" + (f", and {ff[1]}" if len(ff) > 1 else "") + (f" ({form})" if form else "") + "."))
        elif form_s >= 0.48:
            facts.append((70, f"Recent figures are usable — {ff[0]}" + (f"; {form}" if form else "") + "."))
        else:
            facts.append((40, f"Form is ordinary ({form or 'sparse on the card'}), so this is not a pure napkin pick."))
    elif form:
        facts.append((55, f"Card form reads {form}."))

    if trend >= 0.62 and form_s >= 0.45:
        facts.append((72, "The latest runs are better than the older ones — going the right way."))
    elif trend <= 0.38 and form:
        facts.append((50, "The profile is more mixed lately; not a pure improver story."))

    # Weight
    if wdelta is not None:
        if wdelta <= -4:
            facts.append((78, f"Helpful drop in the weights — about {abs(wdelta):.0f}lb lighter than its last win."))
        elif wdelta <= -2:
            facts.append((60, f"Small weight drop ({abs(wdelta):.0f}lb) versus last winning mark."))
        elif wdelta >= 5:
            facts.append((65, f"Up about {wdelta:.0f}lb on its last win — asks more, especially if the trip stretches it."))
        elif wdelta >= 3:
            facts.append((55, f"Carries roughly {wdelta:.0f}lb more than when it last won."))

    # Absence / freshness
    if days is not None:
        if days > 180:
            facts.append((75, f"Off {days} days — long absence, so the fitness question is real."))
        elif days > 100:
            facts.append((58, f"Back from {days} days off; needs to be tuned after the break."))
        elif 14 <= days <= 40:
            facts.append((52, f"Spacing looks normal ({days} days since last)."))
        elif days < 7:
            facts.append((55, f"Quick turnaround ({days} days) — either well-in or rushed."))

    # Connections
    if trainer and t_day >= 3:
        facts.append((68, f"{trainer} has {t_day} on the card today — active yard, not a one-shot entry."))
    elif trainer:
        facts.append((45, f"Trained by {trainer}."))
    if jockey and j_day >= 3:
        facts.append((66, f"{jockey} rides {j_day} today and kept this mount — usually means they want the leg-up."))
    elif jockey:
        facts.append((42, f"{jockey} is booked."))

    # Trip / going / surface (card-level, honest about limits)
    if trip and course:
        facts.append((58, f"Race is {course} over {trip}" + (f" on {going}" if going else "") + "."))
    elif course:
        facts.append((50, f"At {course}" + (f", going {going}" if going else "") + "."))
    if surface == "AW":
        facts.append((48, "All-weather: the form string alone does not prove past AW runs, so do not over-claim the surface angle."))
    elif going:
        g = going.lower()
        if any(x in g for x in ("soft", "heavy", "yielding")):
            facts.append((62, f"Proper soft/testing side of the going ({going}) — stick to horses that handle it, not pure firm-ground speed."))
        elif any(x in g for x in ("firm", "good to firm")):
            facts.append((55, f"Quick ground ({going})."))

    if headgear:
        facts.append((50, f"Headgear noted: {headgear}."))
    if orating is not None:
        facts.append((35, f"OR {orating}."))
    if weight and not any("weight" in f[1].lower() or "lb" in f[1].lower() for f in facts):
        facts.append((30, f"Carries {weight}."))

    # Market / rivals
    if rank == 1 and odds <= 3.5:
        facts.append((70, f"Clear market leader around {odds:.2f} — needs a reason to oppose, not a reason to invent."))
    elif rank == 1:
        facts.append((60, f"Favourite on our prices at about {odds:.2f}."))
    elif fav_name and fav_name != name and fav_odds and odds > fav_odds * 1.4:
        frag = f"Market is around {fav_name} ({fav_odds:.2f})"
        if fav_form:
            frag += f" with form {fav_form}"
        frag += f"; {name} is {odds:.2f}."
        facts.append((74, frag))
    if tip_type == "ew" and field_size >= 8 and odds >= 6:
        facts.append((64, f"Each-way makes sense in a {field_size}-runner field at {odds:.2f}."))
    elif tip_type == "win" and odds <= 4:
        facts.append((50, f"Short enough that win-only is the honest play at {odds:.2f}."))

    if field_size >= 12:
        facts.append((45, f"Big field ({field_size}) — luck in running matters."))
    elif field_size and field_size <= 6:
        facts.append((40, f"Small field ({field_size}) — form should get a fair chance to hold up."))

    # Bot preference: boost certain fact categories by re-sorting with bias
    bias = {
        "FormFox": ("form", "figures", "runs", "won last", "improver", "ordinary"),
        "HotTrainer": ("trained", "yard", "rides", "booked", "mount", "trainer"),
        "ValueHunter": ("market", "favourite", "odds", "each-way", "price"),
        "DevilAdvocate": ("market", "favourite", "oppose", "ordinary", "not"),
        "BloodlineBetty": ("going", "trip", "weight", "absence", "aw", "ground", "lb"),
        "PaceProphet": ("field", "rides", "booked", "shape", "trip", "running"),
    }
    keys = bias.get(bot, ())
    scored = []
    for pri, tx in facts:
        boost = 0
        low = tx.lower()
        for k in keys:
            if k in low:
                boost += 8
        scored.append((pri + boost, tx))
    scored.sort(key=lambda x: -x[0])

    # De-dupe similar lines
    chosen = []
    seen_norm = set()
    for pri, tx in scored:
        nrm = re.sub(r"\s+", " ", tx.lower())[:80]
        if nrm in seen_norm:
            continue
        seen_norm.add(nrm)
        chosen.append(tx)
        if len(chosen) >= 6:
            break

    # Opening line varies by bot + seed
    openers = {
        "FormFox": [
            f"{name} is the form pick for me.",
            f"If you go by the page, {name} is the one that keeps answering.",
            f"I keep coming back to {name} on the figures.",
        ],
        "HotTrainer": [
            f"Connections angle: {name}.",
            f"I am with the {trainer or 'yard'} runner — {name}.",
            f"{name} is the one I want from this yard today.",
        ],
        "ValueHunter": [
            f"Price is the point with {name}.",
            f"At {odds:.2f}, {name} is the side I want.",
            f"I would rather be on {name} than overpay elsewhere.",
        ],
        "DevilAdvocate": [
            f"I am not buying the obvious story here — {name} is the alternative.",
            f"Fade the herd: {name} is more interesting than the crowd horse.",
            f"Against the grain, {name}.",
        ],
        "BloodlineBetty": [
            f"Conditions matter, and {name} fits them better than most.",
            f"{name} for the trip/ground setup.",
            f"On this test, {name} is the practical pick.",
        ],
        "PaceProphet": [
            f"How the race is run helps {name}.",
            f"Race shape points me at {name}.",
            f"{name} looks the right type for this setup.",
        ],
    }
    opts = openers.get(bot) or [f"{name} is the pick."]
    opener = opts[sum(ord(c) for c in seed) % len(opts)]

    # Closing stake line
    if tip_type == "ew":
        close = _h(seed, f"Each-way {name} at about {odds:.2f}.", f"Play {name} each-way around {odds:.2f}.")
    else:
        close = _h(seed, f"Win {name} around {odds:.2f}.", f"Straight win on {name} at about {odds:.2f}.")

    body = " ".join(chosen[:5])
    text = f"{opener} {body} {close}"
    text = " ".join(text.split())

    # Soft minimum length without robotic disclaimer
    if _wc(text) < 40 and form:
        text += f" Form line on the card: {form}."
    if _wc(text) < 40 and trainer and trainer not in text:
        text += f" Trainer: {trainer}."
    return text.strip()



def build_tips_for_races(d, flat_races):
    races_out = []
    meetings = sorted({r.get("course") or "Unknown" for r in flat_races})
    day_books = build_day_books(flat_races)
    hist_index = load_index()
    print(f"History index: {int(hist_index.get('runs') or 0)} past runs")

    for idx, race in enumerate(flat_races):
        raw = [x for x in (race.get("runners") or []) if x.get("name")]
        if not raw:
            continue
        field_size = len(raw)
        all_odds = [max(1.15, float(x.get("odds") or 10)) for x in raw]
        going = race.get("going") or ""
        distance = race.get("distance") or ""
        course = race.get("course") or ""
        race_surface = race.get("surface") or ""
        race_code = race.get("code") or race_code_from_name(race.get("name") or "")
        runners = []
        for x in raw:
            er = enrich(x, field_size, all_odds, going, distance, course, day_books)
            if race_surface:
                er["_surface"] = race_surface
            if race_code:
                er["_code"] = race_code
            else:
                er["_code"] = er.get("_code") or "unknown"
            # History pattern hints (neutral when empty)
            er["_hist_bits"] = []
            er["_hist_used"] = False
            if HAS_HISTORY and int(hist_index.get("runs") or 0) > 0:
                er["_hist_bits"] = horse_history_bits(
                    hist_index,
                    er.get("name") or "",
                    course,
                    er.get("_surface") or "",
                    er.get("_code") or "",
                    going,
                    distance,
                )
                hs = hist_index.get("horse_surface") or {}
                hc = hist_index.get("horse_code") or {}
                hg = hist_index.get("horse_going") or {}
                hd = hist_index.get("horse_distance") or {}
                hcourse = hist_index.get("horse_course") or {}
                tcourse = hist_index.get("trainer_course") or {}
                jtrain = hist_index.get("jockey_trainer") or {}

                rate_s, n_s = lookup(hs, er.get("name") or "", er.get("_surface") or "unknown")
                rate_c, n_c = lookup(hc, er.get("name") or "", er.get("_code") or "unknown")
                if n_s >= 3:
                    er["_form"] = min(0.9, er["_form"] + (rate_s - 0.12) * 0.18)
                    er["_hist_used"] = True
                if n_c >= 3:
                    er["_form"] = min(0.9, er["_form"] + (rate_c - 0.12) * 0.14)
                    er["_hist_used"] = True

                # Align buckets with history_store.going_bucket / distance_bucket
                gf = going_family(going)
                if gf == "softish":
                    gb = "soft"
                elif gf == "quick":
                    gb = "firm"
                elif gf == "AW":
                    gb = "aw"
                elif gf == "good":
                    gb = "good"
                else:
                    gb = "unknown"
                fur = distance_furlongs(distance)
                if fur is None:
                    db = "unknown"
                elif fur < 8.8:   # ~1.1m
                    db = "sprint"
                elif fur < 12.8:  # ~1.6m
                    db = "mile"
                elif fur < 17.6:  # ~2.2m
                    db = "middle"
                elif fur < 22.4:  # ~2.8m
                    db = "staying"
                else:
                    db = "extreme"

                rate_g, n_g = lookup(hg, er.get("name") or "", gb)
                rate_d, n_d = lookup(hd, er.get("name") or "", db)
                rate_hc, n_hc = lookup(hcourse, er.get("name") or "", course)
                if n_g >= 3:
                    er["_going"] = min(0.85, max(0.2, er.get("_going", 0.5) + (rate_g - 0.12) * 0.35))
                    er["_hist_used"] = True
                if n_d >= 3:
                    er["_trip"] = min(0.85, max(0.2, er.get("_trip", 0.5) + (rate_d - 0.12) * 0.35))
                    er["_hist_used"] = True
                if n_hc >= 2:
                    er["_form"] = min(0.9, er["_form"] + (rate_hc - 0.12) * 0.2)
                    er["_hist_used"] = True

                tn = norm_name(er.get("trainer") or "")
                jn = norm_name(er.get("jockey") or "")
                rate_tc, n_tc = lookup(tcourse, tn, course)
                rate_jt, n_jt = lookup(jtrain, jn, tn)
                if n_tc >= 4:
                    er["_trainer"] = min(0.88, max(0.2, er.get("_trainer", 0.5) + (rate_tc - 0.12) * 0.4))
                    er["_hist_used"] = True
                if n_jt >= 4:
                    er["_combo"] = min(0.88, max(0.2, er.get("_combo", 0.5) + (rate_jt - 0.12) * 0.4))
                    er["_hist_used"] = True

                # Plain-English history facts for the tip write-up
                hf = []
                if n_tc >= 4:
                    hf.append(f"{er.get('trainer') or 'This trainer'} is {rate_tc*100:.0f}% (n={n_tc}) at {course} in our results store.")
                if n_jt >= 4:
                    hf.append(f"Jockey–trainer combo {rate_jt*100:.0f}% together from {n_jt} runs we have logged.")
                if n_hc >= 2:
                    hf.append(f"{er.get('name') or 'This horse'} is {rate_hc*100:.0f}% at {course} from {n_hc} runs on file.")
                if n_g >= 3:
                    hf.append(f"On this going band, {rate_g*100:.0f}% from {n_g} runs in our history.")
                if n_d >= 3:
                    hf.append(f"At this sort of trip, {rate_d*100:.0f}% from {n_d} recorded runs.")
                if n_s >= 3:
                    hf.append(f"Surface record in our data: {rate_s*100:.0f}% from {n_s} runs.")
                er["_hist_facts"] = hf
            else:
                er["_hist_facts"] = []
            runners.append(er)
        rng = random.Random(f"{d.isoformat()}|{course}|{race.get('time')}|{idx}")

        tips = []
        for bot in BOT_NAMES:
            ranked = sorted(((score_bot(bot, r, rng), r) for r in runners), key=lambda x: -x[0])
            prob, best, tip_type = pick_for_bot(bot, ranked, field_size)
            conf = max(40, min(84, int(round(prob * 100))))
            tips.append({
                "bot": bot,
                "horse": best["name"],
                "odds": round(best["odds"], 2),
                "conf": conf,
                "type": tip_type,
                "reason": tipster_reason(bot, best, tip_type, conf, field_size, rivals=runners),
            })

        # Stars = how many bots independently chose this horse (agreement is allowed)
        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = counts[t["horse"]]

        races_out.append({
            "course": course or "Unknown",
            "time": race.get("time") or "",
            "name": race.get("name") or "",
            "going": going,
            "distance": distance,
            "surface": race.get("surface") or surface_from(course, going),
            "code": race.get("code") or "unknown",
            "tips": tips,
        })

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Human-style reasons; day trainer/jockey books; surface + trip aware",
    }


def load_scraped_races(d):
    path = DATA_DIR / f"racecards-{d.isoformat()}.json"
    if not path.exists():
        print(f"No racecards file: {path}")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    flat = []
    for m in data.get("meetings") or []:
        course = m.get("course") or "Unknown"
        m_going = m.get("going") or ""
        for r in m.get("races") or []:
            if not r.get("runners"):
                continue
            going = r.get("going") or m_going
            flat.append({
                "course": course,
                "time": r.get("time") or "",
                "name": r.get("name") or "",
                "going": going,
                "distance": r.get("distance") or "",
                "surface": r.get("surface") or "",
                "code": r.get("code") or "",
                "runners": r["runners"],
            })
    return flat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    d = parse_date(args.date)
    print(f"Generating tips for {d.isoformat()}")
    scraped = load_scraped_races(d)
    # Detect unpublished card note from racecards file
    rc_path = DATA_DIR / f"racecards-{d.isoformat()}.json"
    rc_note = None
    rc_published = True
    if rc_path.exists():
        try:
            rc = json.loads(rc_path.read_text(encoding="utf-8"))
            rc_note = rc.get("note")
            if rc.get("published") is False:
                rc_published = False
        except Exception:
            pass

    if not scraped or not rc_published:
        tips = {
            "date": d.isoformat(),
            "meetings": [],
            "races": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "published": False,
            "note": rc_note or "No scraped racecards available — card may not be published yet.",
        }
    else:
        tips = build_tips_for_races(d, scraped)
        tips["published"] = True
    out = DATA_DIR / f"tips-{d.isoformat()}.json"
    out.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out} races={len(tips.get('races') or [])}")
    if tips.get("races"):
        t0 = tips["races"][0]["tips"][0]
        print("Sample reason:", t0["bot"], t0["horse"], "→", t0["reason"][:180])


if __name__ == "__main__":
    main()
