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

    # Race class today vs recent runs (1 = top, 7 = bottom)
    today_class = r.get("_race_class")
    if today_class is None:
        today_class = parse_race_class(r.get("race_class"), str(r.get("_race_name") or ""))
    try:
        today_class = int(today_class) if today_class is not None else None
    except (TypeError, ValueError):
        today_class = None
    tc, recent_c, move = class_move(today_class, r.get("_previous_results") or [])
    r["_race_class"] = tc
    r["_recent_class"] = recent_c
    r["_class_move"] = move  # up | down | similar | ""

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



def parse_race_class(value, race_name: str = "") -> int | None:
    """UK/IRE class 1 (top) .. 7 (bottom). Group/Listed -> 1."""
    if value is not None and str(value).strip() != "":
        s = str(value).strip()
        try:
            n = int(re.sub(r"[^0-9]", "", str(s)) or 0)
            if 1 <= n <= 7:
                return n
        except ValueError:
            pass
        low = s.lower()
        if any(x in low for x in ("group 1", "group 2", "group 3", "grade 1", "grade 2", "grade 3", "listed")):
            return 1
    n = race_name or ""
    m = re.search(r"\bclass\s*([1-7])\b", n, re.I)
    if m:
        return int(m.group(1))
    low = n.lower()
    if re.search(r"\b(group|grade)\s*[123]\b|\blisted\b", low):
        return 1
    return None


def class_move(today: int | None, previous: list) -> tuple:
    """(today_class, typical_recent_class, label) label in up|down|similar|''."""
    if today is None:
        return None, None, ""
    recent = []
    for p in previous or []:
        if not isinstance(p, dict):
            continue
        c = p.get("race_class")
        if c is None:
            c = parse_race_class(None, str(p.get("race_name") or ""))
        try:
            c = int(c) if c is not None else None
        except (TypeError, ValueError):
            c = None
        if c is not None and 1 <= c <= 7:
            recent.append(c)
    if not recent:
        return today, None, ""
    sample = recent[:4]
    mid = sorted(sample)[len(sample) // 2]
    delta = mid - today  # +ve => tougher today
    if delta >= 2:
        return today, mid, "up"
    if delta <= -2:
        return today, mid, "down"
    return today, mid, "similar"


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
    if r.get("_rank") == 1 and r["_form"] >= 0.55:
        s += 0.02

    # --- History rates (hard factors when samples exist) ---
    # enrich may set _hist_trainer_course, _hist_combo, _hist_going, _hist_trip, _hist_n_*
    def _hr(key, nkey, weight=0.08, min_n=4):
        nonlocal s
        n = int(r.get(nkey) or 0)
        rate = r.get(key)
        if rate is None or n < min_n:
            return
        # rate is win rate ~0.05-0.35; centre around 0.12
        s += weight * (float(rate) - 0.12)

    _hr("_hist_tc_rate", "_hist_tc_n", weight=0.10, min_n=4)
    _hr("_hist_combo_rate", "_hist_combo_n", weight=0.08, min_n=4)
    _hr("_hist_going_rate", "_hist_going_n", weight=0.07, min_n=3)
    _hr("_hist_trip_rate", "_hist_trip_n", weight=0.06, min_n=3)
    _hr("_hist_course_rate", "_hist_course_n", weight=0.08, min_n=2)

    # --- Class move + OR interaction ---
    move = r.get("_class_move") or ""
    if move == "up":
        s -= 0.06
        if r.get("_race_class") is not None and r.get("_recent_class") is not None:
            gap = int(r["_recent_class"]) - int(r["_race_class"])
            if gap >= 3:
                s -= 0.05
        if r["_form"] < 0.5:
            s -= 0.03
        # up in class AND carrying more weight vs last win
        if r.get("_weight_delta_lbs") is not None and float(r["_weight_delta_lbs"]) >= 3:
            s -= 0.03
    elif move == "down":
        s += 0.04
        if r["_form"] >= 0.55:
            s += 0.02
        if r.get("_weight_delta_lbs") is not None and float(r["_weight_delta_lbs"]) <= -2:
            s += 0.02  # class drop + weight drop

    # --- Last-run fail ---
    last = (r.get("_form_raw") or r.get("form") or "")[:1]
    if last == "P":
        s -= 0.08
    elif last in ("F", "U", "R", "B"):
        s -= 0.07

    # --- Debut / blank form: tip rarely ---
    form = (r.get("_form_raw") or r.get("form") or "").strip()
    if not form:
        s -= 0.12  # strong caution unless connections rescue it
        if int(r.get("_t_day_n") or 0) >= 3 or int(r.get("_j_day_n") or 0) >= 3:
            s += 0.04  # busy yard/jockey can offset a little

    # --- Race shape ---
    fs = int(r.get("_field_size") or r.get("field_size") or 0)
    if fs >= 12:
        s -= 0.015  # luck in running
        if r["_rank"] <= 2:
            s += 0.01
    elif 0 < fs <= 6:
        s += 0.02 if r["_form"] >= 0.5 else 0.0

    # --- Market vs model (value edge) ---
    # implied win prob from decimal odds; compare to soft model score
    odds = float(r.get("odds") or 10)
    implied = 1.0 / odds if odds > 1 else 0.1
    # map s roughly to 0.05-0.45 chance
    model_p = max(0.04, min(0.45, s * 0.42))
    edge = model_p - implied
    r["_edge"] = round(edge, 4)
    if bot == "ValueHunter":
        s += max(-0.05, min(0.10, edge * 0.5))
        if edge < -0.02:
            s -= 0.04  # overbet for value bot
    elif bot == "DevilAdvocate" and r["_rank"] == 1 and r["_form"] < 0.55:
        s += 0.03  # oppose weak fav

    # Long absence with form evidence only
    days = r.get("_days_off")
    try:
        days = int(days) if days is not None else None
    except (TypeError, ValueError):
        days = None
    if days is not None and days > 180:
        s -= 0.04
    elif days is not None and days > 100:
        s -= 0.02

    s += rng.uniform(-0.02, 0.02)
    return max(0.05, min(0.93, s))




def choose_type(bot, r, field_size, prob):
    odds = r["odds"]
    if field_size < 5 or odds < 5.5:
        return "win"
    if r["_form"] < 0.45:
        return "win"
    if field_size >= 8 and odds >= 7.5 and prob >= 0.32 and r["_form"] >= 0.48:
        return "ew"
    return "win"


def pick_for_bot(bot, ranked, field_size, used_names=None, force_diversity=True):
    """Pick a horse for this bot. Prefer unique picks unless one horse dominates scores."""
    used_names = used_names or set()
    candidates = []
    for prob, r in ranked:
        if r["odds"] >= 16 and r["_form"] < 0.55:
            continue
        if r["odds"] >= 20 and r["_rank"] >= 4 and r["_form"] < 0.6:
            continue
        # blank form: only allow if score still high after debut penalty
        if not (r.get("_form_raw") or r.get("form") or "").strip() and prob < 0.45:
            continue
        candidates.append((prob, r))
    if not candidates:
        candidates = list(ranked)

    # If best is clearly clear of second, allow consensus
    best_p = candidates[0][0] if candidates else 0
    second_p = candidates[1][0] if len(candidates) > 1 else 0
    clear_leader = (best_p - second_p) >= 0.08

    def take(pool):
        for prob, r in pool:
            name = (r.get("name") or "").strip()
            if force_diversity and name in used_names and not clear_leader:
                continue
            tip_type = choose_type(bot, r, field_size, prob)
            # ValueHunter: need non-negative edge unless short field
            if bot == "ValueHunter" and r.get("_edge") is not None and r["_edge"] < -0.03 and r["odds"] < 8:
                continue
            return prob, r, tip_type
        return None

    got = take(candidates)
    if got:
        return got
    # fallback: ignore diversity
    market = [x for x in candidates if x[1]["_rank"] <= max(3, field_size // 2)]
    pool = market or candidates or ranked
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
    OLBG-style prose: 2–4 short sentences, one coherent angle.
    Only uses card fields + history facts we actually have.
    """
    name = (r.get("name") or "This horse").strip()
    odds = float(r.get("odds") or 10)
    form = (r.get("_form_raw") or r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    course = (r.get("_course") or "").strip()
    going = (r.get("_going_txt") or "").strip()
    trip = (r.get("_trip_txt") or "").strip()
    surface = r.get("_surface") or "unknown"
    rank = int(r.get("_rank") or 0)
    form_s = float(r.get("_form") or 0.4)
    t_day = int(r.get("_t_day_n") or 0)
    j_day = int(r.get("_j_day_n") or 0)
    hist_facts = list(r.get("_hist_facts") or [])
    hist_bits = list(r.get("_hist_bits") or [])
    weight = (r.get("_weight") or r.get("weight") or "").strip()
    wdelta = r.get("_weight_delta_lbs")
    days = r.get("_days_off")
    try:
        days = int(days) if days is not None else None
    except (TypeError, ValueError):
        days = None
    orating = r.get("_or") if r.get("_or") is not None else r.get("official_rating")
    try:
        orating = int(orating) if orating is not None else None
    except (TypeError, ValueError):
        orating = None
    headgear = r.get("_headgear") or r.get("headgear") or ""
    first_time_hg = bool(r.get("headgear_first_time") or r.get("_headgear_first_time"))
    if isinstance(headgear, dict):
        hg_name = str(headgear.get("name") or headgear.get("symbol") or "").strip()
        try:
            hg_count = int(headgear.get("count") or 0)
        except (TypeError, ValueError):
            hg_count = 0
        if hg_count == 1:
            first_time_hg = True
        headgear = hg_name
    else:
        headgear = str(headgear).strip()
        if not first_time_hg:
            first_time_hg = bool(headgear) and any(
                x in headgear.lower() for x in ("1st", "first time", "first-time")
            )
    last_code = (form[:1] if form else "") or str(r.get("last_run_code") or "")
    last_cas = str(r.get("last_run_casualty") or "").strip()
    prev = r.get("_previous_results") or r.get("previous_results") or []
    if not isinstance(prev, list):
        prev = []

    seed = f"{bot}|{name}|{course}|{rank}|{odds:.2f}"

    # --- concrete angles from previous runs ---
    course_runs = []
    trip_hint = ""
    last_run = prev[0] if prev else None
    for p in prev:
        if not isinstance(p, dict):
            continue
        pc = str(p.get("course") or "")
        if course and pc and course.lower() in pc.lower():
            course_runs.append(p)
    best_course = None
    for p in course_runs:
        pos = p.get("position")
        try:
            pi = int(pos)
        except (TypeError, ValueError):
            pi = None
        if pi is not None and pi <= 3:
            best_course = p
            break
    if not best_course and course_runs:
        best_course = course_runs[0]

    # Favourite rival for contrast
    fav_name, fav_odds = "", 0.0
    if rivals:
        try:
            ordered = sorted(rivals, key=lambda x: float(x.get("odds") or 99))
            if ordered and ordered[0].get("name") != name:
                fav_name = (ordered[0].get("name") or "").strip()
                fav_odds = float(ordered[0].get("odds") or 0)
        except Exception:
            pass

    # Build 1 primary angle + supporting clause
    angles = []  # sentences

    # Last-run disaster gets priority honesty
    if last_code == "P":
        angles.append(
            f"{name} pulled up last time"
            + (f" ({last_cas})" if last_cas else "")
            + " — that has to be respected, so this is only of interest if the price overstates the risk."
        )
    elif last_code == "F":
        angles.append(f"{name} fell last time out, so any support has to allow for that risk.")
    elif last_code == "U":
        angles.append(f"{name} unseated last time; the complete-the-race question is real.")

    # Class rise / drop (only when we have numbers)
    move = r.get("_class_move") or ""
    tc = r.get("_race_class")
    recent_c = r.get("_recent_class")
    if move == "up" and tc is not None and recent_c is not None:
        angles.append(
            f"This is a step up in grade — Class {tc} today against recent Class {recent_c} form — so improvement is required, not assumed."
        )
    elif move == "down" and tc is not None and recent_c is not None:
        angles.append(
            f"Eased in class (Class {tc} today vs recent Class {recent_c}), which can help if the ability is still there."
        )
    elif tc is not None and not move and recent_c is None:
        # today known but no past classes — still mention lightly if Class 1-2
        if int(tc) <= 2:
            angles.append(f"Operating in Class {tc} company today.")

    # Course / C&D style
    if best_course and not angles:
        pos = best_course.get("position")
        try:
            pi = int(pos)
        except (TypeError, ValueError):
            pi = None
        when = str(best_course.get("date") or "")
        dist = str(best_course.get("distance") or "")
        if pi == 1:
            angles.append(
                f"{name} has already won at {course}"
                + (f" over {dist}" if dist else "")
                + (f" ({when})" if when else "")
                + ", so the track holds no mysteries."
            )
        elif pi is not None and pi <= 3:
            angles.append(
                f"{name} has solid course form at {course}"
                + (f" — {pi}{'st' if pi==1 else 'nd' if pi==2 else 'rd' if pi==3 else 'th'} over {dist}" if dist else f" (finished {pi})")
                + ", which matters more than a cold form string."
            )

    # Handicap / OR
    if orating is not None and form_s >= 0.4:
        if orating <= 70 and tip_type == "ew":
            angles.append(
                f"Off a mark of {orating} there is room to be competitive if the handicapper has been kind."
            )
        elif orating:
            angles.append(f"Rated {orating} for this.")

    # Headgear
    if headgear:
        if first_time_hg:
            angles.append(
                f"First-time {headgear.lower()} could help sharpen things up if the gear has the usual effect."
            )
        else:
            angles.append(f"Runs in {headgear.lower()}.")

    # Trainer / jockey bookings
    conn = []
    if trainer and t_day >= 3:
        conn.append(f"{trainer} is busy today ({t_day} on the card)")
    elif trainer:
        conn.append(f"trained by {trainer}")
    if jockey and j_day >= 3:
        conn.append(f"{jockey} keeps the mount among {j_day} rides")
    elif jockey:
        conn.append(f"{jockey} rides")
    if conn and len(angles) < 3:
        # keep proper-case names (avoid str.capitalize — it lowercases "Appleby")
        if len(conn) == 1:
            angles.append(conn[0][0].upper() + conn[0][1:] + ".")
        else:
            angles.append(conn[0][0].upper() + conn[0][1:] + ", and " + conn[1] + ".")

    # History one-liner if present
    if hist_facts and len(angles) < 3:
        angles.append(hist_facts[0])
    elif hist_bits and len(angles) < 3:
        angles.append(hist_bits[0] if hist_bits[0].endswith(".") else hist_bits[0] + ".")

    # Last run narrative if still thin
    if last_run and len(angles) < 2:
        lp = last_run.get("position")
        lc = str(last_run.get("course") or "")
        ld = str(last_run.get("distance") or "")
        try:
            lpi = int(lp)
        except (TypeError, ValueError):
            lpi = None
        if lpi is not None:
            angles.append(
                f"Latest start: {lpi}{'st' if lpi==1 else 'nd' if lpi==2 else 'rd' if lpi==3 else 'th'}"
                + (f" at {lc}" if lc else "")
                + (f" over {ld}" if ld else "")
                + "."
            )

    # Weight only if trusted
    if wdelta is not None and abs(float(wdelta)) <= 12 and abs(float(wdelta)) >= 3 and len(angles) < 3:
        if wdelta <= -3:
            angles.append(
                f"A {abs(float(wdelta)):.0f}lb drop versus a comparable winning weight on the card is a genuine help."
            )
        elif wdelta >= 3:
            angles.append(
                f"Up about {float(wdelta):.0f}lb on a comparable winning weight from the card."
            )

    # Absence only if real
    if days is not None and days > 100 and len(angles) < 3:
        angles.append(f"Back from {days} days off — fitness has to be taken on trust.")

    # Conditions
    if going and surface != "AW" and len(angles) < 3:
        gl = going.lower()
        if any(x in gl for x in ("soft", "heavy", "yielding")):
            angles.append(f"Conditions ({going}) look testing; horses that handle this ground get preferred.")
    if surface == "AW" and any("poly" in str(p.get("going") or "").lower() or "standard" in str(p.get("going") or "").lower() or "lingfield" in str(p.get("course") or "").lower() or "wolverhampton" in str(p.get("course") or "").lower() or "southwell" in str(p.get("course") or "").lower() for p in prev[:4]):
        if len(angles) < 3:
            angles.append("Has all-weather experience on the card already, so the surface itself is not a complete unknown.")

    # Market contrast
    if fav_name and fav_odds and odds >= fav_odds * 1.8 and tip_type == "ew" and len(angles) < 3:
        angles.append(
            f"The market is around {fav_name} ({fav_odds:.2f}); at {odds:.2f} {name} is the each-way price that still has a case."
        )

    # Form line as support, not the whole tip
    if form and form_s >= 0.55 and not any("form" in a.lower() or "latest start" in a.lower() for a in angles):
        ff = _form_facts(form)
        if ff:
            angles.append(f"Recent figures ({form}) back the idea: {ff[0]}.")

    # Fallback if almost empty
    if not angles:
        if form:
            angles.append(f"{name} makes the shortlist on the card form {form}.")
        elif trainer:
            angles.append(f"{name} is the {trainer} runner that makes most appeal on this page.")
        else:
            angles.append(f"{name} is the pick on the available card data.")

    # Voice: light opener by bot without template spam
    openers = {
        "FormFox": f"{name} is the form angle for me.",
        "HotTrainer": f"Connections lean me toward {name}.",
        "ValueHunter": f"{name} is the price that interests me.",
        "DevilAdvocate": f"I prefer {name} to the more obvious horses.",
        "BloodlineBetty": f"{name} fits the conditions better than most.",
        "PaceProphet": f"{name} for how this race should be run.",
    }
    opener = openers.get(bot, f"{name} is the pick.")
    # If first angle already starts with name, skip opener sometimes
    use_opener = not angles[0].startswith(name)

    # Closing stake line — soft, like OLBG
    if tip_type == "ew":
        close = f"Each-way at around {odds:.2f} looks the sensible way to play it."
    else:
        close = f"Worth a win bet at around {odds:.2f}."

    parts = []
    if use_opener:
        parts.append(opener)
    # max 3 angles + close
    for a in angles[:3]:
        a = a.strip()
        if not a.endswith((".", "!", "?")):
            a += "."
        parts.append(a)
    parts.append(close)

    text_out = " ".join(parts)
    text_out = " ".join(text_out.split())
    return text_out



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
            # Attach today's race class (from meeting list / race name)
            rc_today = race.get("race_class")
            if rc_today is None:
                rc_today = parse_race_class(None, race.get("name") or "")
            er["_race_class"] = rc_today
            er["_race_name"] = race.get("name") or ""
            # Recompute class move now that today class is known
            tc, recent_c, move = class_move(rc_today, er.get("_previous_results") or [])
            er["_race_class"] = tc
            er["_recent_class"] = recent_c
            er["_class_move"] = move
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

                er["_hist_tc_rate"] = rate_tc if n_tc else None
                er["_hist_tc_n"] = n_tc
                er["_hist_combo_rate"] = rate_jt if n_jt else None
                er["_hist_combo_n"] = n_jt
                er["_hist_course_rate"] = rate_hc if n_hc else None
                er["_hist_course_n"] = n_hc
                er["_hist_going_rate"] = rate_g if n_g else None
                er["_hist_going_n"] = n_g
                er["_hist_trip_rate"] = rate_d if n_d else None
                er["_hist_trip_n"] = n_d

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
        used = set()
        for bot in BOT_NAMES:
            ranked = sorted(((score_bot(bot, r, rng), r) for r in runners), key=lambda x: -x[0])
            # recompute edges for value after ranking list built
            for prob, r in ranked:
                if r.get("_edge") is None:
                    odds = float(r.get("odds") or 10)
                    implied = 1.0 / odds if odds > 1 else 0.1
                    model_p = max(0.04, min(0.45, prob * 0.42))
                    r["_edge"] = round(model_p - implied, 4)
            prob, best, tip_type = pick_for_bot(bot, ranked, field_size, used_names=used, force_diversity=True)
            conf = max(40, min(84, int(round(prob * 100))))
            tips.append({
                "bot": bot,
                "horse": best["name"],
                "odds": round(best["odds"], 2),
                "conf": conf,
                "type": tip_type,
                "edge": best.get("_edge"),
                "class_move": best.get("_class_move") or "",
                "reason": tipster_reason(bot, best, tip_type, conf, field_size, rivals=runners),
            })
            used.add((best.get("name") or "").strip())

        # Stars = how many bots independently chose this horse
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
            "race_class": race.get("race_class"),
            "tips": tips,
        })

    # --- Daily Hot Picks: 3+ bots, avg conf >= 55, not pure longshot spam ---
    horse_agg = {}
    for race in races_out:
        for t in race.get("tips") or []:
            key = (race.get("course"), race.get("time"), t.get("horse"))
            horse_agg.setdefault(key, {
                "course": race.get("course"),
                "time": race.get("time"),
                "name": race.get("name"),
                "horse": t.get("horse"),
                "odds": t.get("odds"),
                "bots": [],
                "confs": [],
                "types": [],
            })
            horse_agg[key]["bots"].append(t.get("bot"))
            horse_agg[key]["confs"].append(int(t.get("conf") or 0))
            horse_agg[key]["types"].append(t.get("type") or "win")
            horse_agg[key]["odds"] = t.get("odds")

    hot = []
    for key, v in horse_agg.items():
        n = len(v["bots"])
        if n < 3:
            continue
        avg_conf = sum(v["confs"]) / max(1, n)
        if avg_conf < 55:
            continue
        odds = float(v.get("odds") or 99)
        if odds >= 21 and n < 4:
            continue  # need strong agreement on big prices
        hot.append({
            "course": v["course"],
            "time": v["time"],
            "race": v["name"],
            "horse": v["horse"],
            "odds": v["odds"],
            "bots": v["bots"],
            "bot_count": n,
            "avg_conf": round(avg_conf, 1),
            "type": "ew" if v["types"].count("ew") > v["types"].count("win") else "win",
            "score": round(n * 10 + avg_conf + max(0, 12 - odds), 2),
        })
    hot.sort(key=lambda x: -x["score"])
    hot = hot[:12]

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "hot_picks": hot,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "History-weighted scores; class moves; diversity picks; hot picks need 3+ bots & conf≥55",
        "meta": {
            "history_runs": int(hist_index.get("runs") or 0),
            "hot_pick_rules": "min_bots=3, min_avg_conf=55",
        },
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
                "race_class": r.get("race_class"),
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
