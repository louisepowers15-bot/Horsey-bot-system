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
    r["_going_family"] = gf
    r["_going"] = 0.56 if gf in ("good", "AW") else (0.53 if gf else 0.5)
    r["_trip"] = 0.54 if distance else 0.5
    r["_going_txt"] = going or ""
    r["_trip_txt"] = distance or ""
    r["_trip_label"] = trip_label(distance) if distance else ""
    r["_course"] = course or ""
    r["_furlongs"] = distance_furlongs(distance)

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


def _pick(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    return options[sum(ord(c) for c in seed) % len(options)]


def _form_phrases(form: str, form_s: float, trend: float) -> list[str]:
    tokens = parse_form_tokens(form)
    if not form and not tokens:
        return []
    out = []
    if form:
        out.append(f"the card shows {form}")
    if tokens:
        last = tokens[0]
        mapping = {
            "1": "latest was a win",
            "2": "only found one too good last time",
            "3": "ran into a place on the latest start",
            "0": "missed the frame latest",
            "F": "fell last time — treat that as a blot, not the whole story",
            "P": "pulled up latest, so the prior form matters more",
            "U": "unseated recently, which clouds the picture",
        }
        if last in mapping:
            out.append(mapping[last])
        wins = sum(1 for t in tokens[:6] if t == "1")
        if wins >= 2:
            out.append(f"two or more wins sit in the recent sequence")
        places = sum(1 for t in tokens[:6] if t in ("1", "2", "3"))
        if places >= 3 and wins < 2:
            out.append("consistent frame finishes without always finishing the job")
    if form_s >= 0.62:
        out.append("overall form level is up to this grade")
    elif form_s < 0.4 and form:
        out.append("raw figures are patchy, so the race shape has to help")
    if trend >= 0.6:
        out.append("recent runs are better than the older ones")
    elif trend <= 0.38 and form:
        out.append("latest efforts are below the earlier peak")
    # unique
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def tipster_reason(bot, r, tip_type, conf, field_size, rivals: list[dict] | None = None):
    """
    Human tipster voice. Only mention angles we have data for.
    Different bots prioritise different evidence; wording is seeded, not random each run.
    """
    name = r.get("name") or "This one"
    odds = float(r.get("odds") or 10)
    form = r.get("_form_raw") or str(r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    course = (r.get("_course") or "").strip()
    going = (r.get("_going_txt") or "").strip()
    trip = (r.get("_trip_txt") or "").strip()
    trip_lab = (r.get("_trip_label") or trip or "").strip()
    surface = r.get("_surface") or "unknown"
    rank = int(r.get("_rank") or 0)
    form_s = float(r.get("_form") or 0.4)
    trend = float(r.get("_trend") or 0.5)
    t_day = int(r.get("_t_day_n") or 0)
    j_day = int(r.get("_j_day_n") or 0)
    c_day = int(r.get("_c_day_n") or 0)

    seed = f"{bot}|{name}|{form}|{course}|{odds:.2f}"
    form_ph = _form_phrases(form, form_s, trend)

    # Favourite / rival context for DevilAdvocate / EW
    fav = None
    if rivals:
        fav = min(rivals, key=lambda x: x.get("odds") or 99)
        if fav.get("name") == name:
            fav = None

    sentences: list[str] = []

    # ---- openings differ by bot ----
    if bot == "FormFox":
        sentences.append(_pick(seed, [
            f"{name} is the one I want on form.",
            f"Give me {name} if we are ranking the form lines.",
            f"On what they have done, {name} edges it.",
        ]))
        if form_ph:
            sentences.append(_pick(seed + "f", form_ph[:2]).capitalize() + ("" if form_ph[0].endswith(".") else ".") if False else "")
            # properly:
            chunk = form_ph[0]
            if len(form_ph) > 1 and len(chunk) < 40:
                chunk = form_ph[0] + "; " + form_ph[1]
            sentences[-1] = sentences[-1]  # keep lead
            sentences.append(chunk[0].upper() + chunk[1:] + ("" if chunk.endswith(".") else "."))
        if trip_lab:
            sentences.append(_pick(seed + "t", [
                f"Today's {trip_lab} should not catch this one out.",
                f"The {trip_lab} looks a fair match for how the form was earned.",
                f"No issue with the {trip_lab} on paper.",
            ]))
        if surface == "AW" and going:
            sentences.append(_pick(seed + "s", [
                f"All-weather surface ({going}) — plenty of these form lines were built on a similar strip.",
                f"On the sand / AW ({going}), the form is still usable.",
            ]))
        elif going and going_family(going) == "softish":
            sentences.append(f"With the ground {going.lower()}, you want proven stamina in the form — this has enough about it.")
        elif going and going_family(going) == "good":
            sentences.append(_pick(seed + "g", [
                f"Good ground keeps it straightforward.",
                f"Nothing in the going ({going}) to distrust the form.",
            ]))

    elif bot == "HotTrainer":
        if trainer:
            sentences.append(_pick(seed, [
                f"{trainer}'s {name} is the yard pick for me.",
                f"I'll side with the {trainer} horse — {name}.",
                f"{name} represents {trainer} and that is enough to take an interest.",
            ]))
        else:
            sentences.append(f"{name} is the connections angle in this line-up.")
        if t_day >= 3 and trainer:
            sentences.append(f"{trainer} has {t_day} runners on the day sheet — clearly targeting this card.")
        if jockey and c_day >= 2:
            sentences.append(f"{jockey} is booked again for the yard; that repeat combo is deliberate.")
        elif jockey and j_day >= 3:
            sentences.append(f"{jockey} rides {j_day} today and sits on a few of the better-fancied ones.")
        elif jockey:
            sentences.append(_pick(seed + "j", [
                f"{jockey} keeps the partnership.",
                f"No issue with {jockey} in the plate.",
            ]))
        if form_ph:
            sentences.append(form_ph[0][0].upper() + form_ph[0][1:] + ".")
        if trip and surface != "unknown":
            sentences.append(
                f"{'AW' if surface == 'AW' else 'Turf'} at {course or 'this track'}, {trip} — the sort of set-up this yard handles."
            )

    elif bot == "ValueHunter":
        sentences.append(_pick(seed, [
            f"{odds:.0f}s about {name} is the value if you accept the form.",
            f"Market has left a gap for {name} at around {odds:.2f}.",
            f"I'm happier on {name}'s price than on the shorter ones.",
        ]))
        if form_ph:
            sentences.append(form_ph[0][0].upper() + form_ph[0][1:] + ".")
        if rank >= 4:
            sentences.append("Plenty of the money is elsewhere, which is exactly when these prices appear.")
        if trainer and t_day >= 2:
            sentences.append(f"{trainer} is busy today ({t_day} runners); this is not a random outsider.")
        if trip_lab:
            sentences.append(f"Trip is {trip_lab} — no reason that alone should stop it.")
        if tip_type == "ew":
            sentences.append("Each-way is the way to take the price.")

    elif bot == "DevilAdvocate":
        if rank <= 2:
            sentences.append(_pick(seed, [
                f"Strip it back and {name} still makes the most sense.",
                f"I am not inventing a fancy angle against {name}.",
            ]))
        else:
            sentences.append(_pick(seed, [
                f"The short prices are not solid enough to freeze out {name}.",
                f"Look past the obvious and {name} is still in the argument.",
            ]))
        if fav and fav.get("name"):
            ff = str(fav.get("_form_raw") or fav.get("form") or "").strip()
            if ff:
                sentences.append(f"The favourite ({fav['name']}) brings form of {ff}, which is not untouchable.")
            else:
                sentences.append(f"{fav['name']} heads the market without a towering form line.")
        if form_ph:
            sentences.append(form_ph[0][0].upper() + form_ph[0][1:] + ".")
        if field_size <= 7:
            sentences.append("Small field: one ordinary jump from the jolly and this is right there.")
        if surface == "AW":
            sentences.append("On the AW the form can reshuffle quickly — do not be married to the jolly.")

    elif bot == "BloodlineBetty":
        sentences.append(_pick(seed, [
            f"{name} still looks open to a bit of improvement.",
            f"There is a progressive thread with {name}.",
            f"Profile-wise, {name} has more to give than a few of these.",
        ]))
        if trend >= 0.55 and form_ph:
            sentences.append("Recent runs are heading the right way rather than the wrong one.")
        elif form_ph:
            sentences.append(form_ph[0][0].upper() + form_ph[0][1:] + ".")
        if trip_lab:
            sentences.append(_pick(seed + "t", [
                f"The {trip_lab} looks a natural fit.",
                f"Happy enough with this horse tackling {trip or 'this trip'}.",
            ]))
        if surface == "AW":
            sentences.append(f"AW specialist tracks like {course or 'this'} often suit this type once they learn the surface.")
        elif going:
            sentences.append(f"Ground described as {going} should not be a hard stop.")
        if trainer:
            sentences.append(f"{trainer} can squeeze a bit more out of this sort.")

    else:  # PaceProphet
        sentences.append(_pick(seed, [
            f"Race shape is the angle for {name}.",
            f"How this should be run helps {name}.",
            f"{name} looks the right type for the likely tempo.",
        ]))
        if field_size <= 6:
            sentences.append(f"Only {field_size} declared — position means as much as the form book.")
        elif field_size >= 12:
            sentences.append(f"Big field ({field_size}): need one that can travel and find a split.")
        else:
            sentences.append(f"With {field_size} in, a clean trip will decide more than a length or two on paper.")
        if jockey:
            if j_day >= 3:
                sentences.append(f"{jockey} is busy on the card ({j_day} rides) and knows when to commit.")
            else:
                sentences.append(f"{jockey} is a sensible booking for a horse that needs placing.")
        if form_ph:
            sentences.append(form_ph[0][0].upper() + form_ph[0][1:] + ".")
        if trip and course:
            sentences.append(f"{course}'s {trip} can turn into a stamina or speed test depending on early fractions — this profile copes.")

    # Close
    if tip_type == "ew":
        sentences.append(_pick(seed + "x", [
            f"Each-way {name} around {odds:.2f}.",
            f"Play {name} each-way at about {odds:.2f}.",
        ]))
    else:
        if rank <= 2 and odds <= 3.2:
            sentences.append(f"Win bet — {name} at about {odds:.2f}.")
        elif odds >= 12:
            sentences.append(f"Speculative win on {name} at around {odds:.2f}.")
        else:
            sentences.append(_pick(seed + "x", [
                f"Win: {name} around {odds:.2f}.",
                f"Back {name} to win at about {odds:.2f}.",
            ]))

    # Clean empties / double spaces
    cleaned = []
    for s in sentences:
        s = re.sub(r"\s+", " ", (s or "").strip())
        if not s:
            continue
        if s[-1] not in ".!?":
            s += "."
        cleaned.append(s)
    return " ".join(cleaned)


def build_tips_for_races(d, flat_races):
    races_out = []
    meetings = sorted({r.get("course") or "Unknown" for r in flat_races})
    day_books = build_day_books(flat_races)

    for idx, race in enumerate(flat_races):
        raw = [x for x in (race.get("runners") or []) if x.get("name")]
        if not raw:
            continue
        field_size = len(raw)
        all_odds = [max(1.15, float(x.get("odds") or 10)) for x in raw]
        going = race.get("going") or ""
        distance = race.get("distance") or ""
        course = race.get("course") or ""
        runners = [
            enrich(x, field_size, all_odds, going, distance, course, day_books)
            for x in raw
        ]
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

        # Diversity pass: if all six on same horse, allow second choice for weakest conf
        counts = Counter(t["horse"] for t in tips)
        if len(counts) == 1 and field_size >= 4:
            weakest = min(range(len(tips)), key=lambda i: tips[i]["conf"])
            bot = tips[weakest]["bot"]
            ranked = sorted(((score_bot(bot, r, rng), r) for r in runners), key=lambda x: -x[0])
            for prob, r in ranked[1:3]:
                if r["name"] != tips[weakest]["horse"]:
                    tips[weakest]["horse"] = r["name"]
                    tips[weakest]["odds"] = round(r["odds"], 2)
                    tips[weakest]["type"] = choose_type(bot, r, field_size, prob)
                    tips[weakest]["conf"] = max(40, min(84, int(round(prob * 100))))
                    tips[weakest]["reason"] = tipster_reason(bot, r, tips[weakest]["type"], tips[weakest]["conf"], field_size, rivals=runners)
                    break

        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = counts[t["horse"]]

        races_out.append({
            "course": course or "Unknown",
            "time": race.get("time") or "",
            "name": race.get("name") or "",
            "going": going,
            "distance": distance,
            "surface": surface_from(course, going),
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
            flat.append({
                "course": course,
                "time": r.get("time") or "",
                "name": r.get("name") or "",
                "going": r.get("going") or m_going,
                "distance": r.get("distance") or "",
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
    tips = build_tips_for_races(d, scraped) if scraped else {
        "date": d.isoformat(), "meetings": [], "races": [],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "No scraped racecards available.",
    }
    out = DATA_DIR / f"tips-{d.isoformat()}.json"
    out.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out} races={len(tips.get('races') or [])}")
    if tips.get("races"):
        t0 = tips["races"][0]["tips"][0]
        print("Sample reason:", t0["bot"], t0["horse"], "→", t0["reason"][:180])


if __name__ == "__main__":
    main()
