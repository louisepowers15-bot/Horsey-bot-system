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




def _h(seed: str, *opts: str) -> str:
    """Deterministic pick so the same tip stays stable across regenerations."""
    opts = [o for o in opts if o]
    if not opts:
        return ""
    return opts[sum(ord(c) for c in seed) % len(opts)]


def _form_story(form: str) -> dict:
    """Concrete notes from a form string only — nothing invented."""
    tokens = parse_form_tokens(form)
    story = {
        "raw": (form or "").strip(),
        "tokens": tokens,
        "last": tokens[0] if tokens else "",
        "wins": sum(1 for t in tokens[:6] if t == "1"),
        "places": sum(1 for t in tokens[:6] if t in ("1", "2", "3")),
        "fails": sum(1 for t in tokens[:6] if t in ("F", "P", "U", "R", "B")),
        "notes": [],
    }
    if not tokens:
        return story
    last = tokens[0]
    if last == "1":
        story["notes"].append("won on the latest start")
    elif last == "2":
        story["notes"].append("finished second last time out")
    elif last == "3":
        story["notes"].append("finished third last time out")
    elif last == "0":
        story["notes"].append("was outside the places on the latest start")
    elif last == "F":
        story["notes"].append("fell last time out")
    elif last == "P":
        story["notes"].append("pulled up last time out")
    elif last == "U":
        story["notes"].append("unseated the rider last time out")
    elif last in ("R", "B"):
        story["notes"].append("failed to complete last time out")
    if story["wins"] >= 2:
        story["notes"].append(f"has {story['wins']} wins among the recent figures")
    elif story["places"] >= 3:
        story["notes"].append(f"has been in the first three {story['places']} times in the recent sequence")
    if story["fails"] and story["wins"]:
        story["notes"].append("shows both winning form and a non-completion in the same recent run of results")
    return story


def _wc(text: str) -> int:
    return len([w for w in text.replace(".", " ").split() if w])


def tipster_reason(bot, r, tip_type, conf, field_size, rivals: list | None = None):
    """
    Full tipster-style reasoning (minimum ~50 words), built only from data
    present on the free card / day book. No invented course stats, no fictional runs.
    """
    name = (r.get("name") or "This horse").strip()
    odds = float(r.get("odds") or 10)
    form = (r.get("_form_raw") or r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    course = (r.get("_course") or "").strip()
    going = (r.get("_going_txt") or "").strip()
    trip = (r.get("_trip_txt") or "").strip()
    trip_lab = (r.get("_trip_label") or "").strip()
    surface = r.get("_surface") or "unknown"
    rank = int(r.get("_rank") or 0)
    form_s = float(r.get("_form") or 0.4)
    trend = float(r.get("_trend") or 0.5)
    t_day = int(r.get("_t_day_n") or 0)
    j_day = int(r.get("_j_day_n") or 0)
    c_day = int(r.get("_c_day_n") or 0)
    seed = f"{bot}|{name}|{form}|{course}|{odds:.2f}|{rank}"

    fs = _form_story(form)
    parts: list[str] = []

    fav = None
    if rivals:
        fav = min(rivals, key=lambda x: float(x.get("odds") or 99))
        if (fav.get("name") or "") == name:
            fav = None

    # --- shared factual blocks (only if data exists) ---
    form_block = ""
    if form:
        detail = "; ".join(fs["notes"][:3]) if fs["notes"] else ""
        if detail:
            form_block = f"The form line is {form} ({detail})."
        else:
            form_block = f"The form line is {form}."
        if trend >= 0.6:
            form_block += " The more recent figures look stronger than the older ones in that sequence."
        elif trend <= 0.38:
            form_block += " The latest figures are not as strong as earlier efforts in the same sequence."
        if form_s >= 0.58:
            form_block += " On balance that level is competitive for this grade of race."
        elif form_s < 0.4:
            form_block += " The figures are not strong in isolation, so the rest of the case has to carry the selection."
    else:
        form_block = (
            f"There is little or no published form string for {name} on this card, "
            "so the case has to rest on connections, trip, surface and the shape of the race rather than a deep form book."
        )

    conn_block = ""
    if trainer or jockey:
        bits = []
        if trainer:
            bits.append(f"trained by {trainer}")
            if t_day >= 2:
                bits.append(f"{trainer} has {t_day} runners on today's card")
        if jockey:
            bits.append(f"ridden by {jockey}")
            if j_day >= 2:
                bits.append(f"{jockey} has {j_day} booked rides today")
        if trainer and jockey and c_day >= 2:
            bits.append(f"the {jockey} / {trainer} pairing appears more than once on the day")
        conn_block = "Connections: " + "; ".join(bits) + "."

    cond_block = ""
    cond_bits = []
    if course:
        cond_bits.append(f"the race is at {course}")
    if trip:
        if trip_lab:
            cond_bits.append(f"over {trip} ({trip_lab})")
        else:
            cond_bits.append(f"over {trip}")
    if surface == "AW":
        cond_bits.append(f"on the all-weather" + (f" (going: {going})" if going else ""))
    elif going:
        cond_bits.append(f"on {going} ground")
    if field_size:
        cond_bits.append(f"in a field of {field_size}")
    if rank:
        if rank == 1:
            cond_bits.append(f"currently around the head of the market at about {odds:.2f}")
        else:
            cond_bits.append(f"available at about {odds:.2f} (market position roughly {rank})")
    if cond_bits:
        cond_block = "Race conditions: " + ", ".join(cond_bits) + "."

    rival_block = ""
    if fav and fav.get("name"):
        ff = (fav.get("_form_raw") or fav.get("form") or "").strip()
        fo = float(fav.get("odds") or 0)
        if ff:
            rival_block = (
                f"The market leader is {fav['name']} (about {fo:.2f}) with form {ff}; "
                "that is useful context but not an automatic reason to dismiss everything else."
            )
        else:
            rival_block = (
                f"The market leader is {fav['name']} (about {fo:.2f}) without a strong published form line on this card."
            )

    # --- bot-specific framing (interpretation only of the above facts) ---
    if bot == "FormFox":
        parts.append(
            f"{name} is selected primarily on the form that is actually printed on the card, "
            f"not on reputation or a single speculative angle."
        )
        parts.append(form_block)
        if cond_block:
            parts.append(cond_block)
        if conn_block:
            parts.append(conn_block)
        parts.append(
            "If the recent figures are a fair guide to today's ability, this is the line that holds up best "
            "when the race is reduced to what each horse has already done."
        )

    elif bot == "HotTrainer":
        parts.append(
            f"{name} is the selection from a connections angle"
            + (f", representing {trainer}" if trainer else "")
            + "."
        )
        if conn_block:
            parts.append(conn_block)
        else:
            parts.append("Trainer and jockey details on the card are limited, so the placement itself is the main clue.")
        parts.append(form_block)
        if cond_block:
            parts.append(cond_block)
        if t_day >= 3 and trainer:
            parts.append(
                f"A yard bringing {t_day} runners on the same day is treating this meeting as a target, "
                f"which is a concrete piece of information rather than a guess about private opinion."
            )
        parts.append(
            "The case is that a deliberate booking and a busy day sheet, combined with usable form, "
            "is a more reliable guide than chasing an unproven outsider."
        )

    elif bot == "ValueHunter":
        parts.append(
            f"The case for {name} is price relative to the form and setup that are actually on the card. "
            f"At about {odds:.2f} the market is not pricing this as a pure favourite, which only matters if the figures support a bigger run than that implies."
        )
        parts.append(form_block)
        if conn_block:
            parts.append(conn_block)
        if cond_block:
            parts.append(cond_block)
        if rank >= 4:
            parts.append(
                "Being further down the betting than several rivals is acceptable when the published form "
                "does not clearly justify those shorter prices."
            )
        parts.append(
            "This is not an invented 'plot' angle; it is a judgement that the available form and conditions "
            "are good enough to take the quoted price rather than lay it."
        )

    elif bot == "DevilAdvocate":
        parts.append(
            f"The selection is {name}, on the basis that the more obvious names in the race are not fully covered by the form that is published today."
        )
        if rival_block:
            parts.append(rival_block)
        parts.append(form_block)
        if cond_block:
            parts.append(cond_block)
        if conn_block:
            parts.append(conn_block)
        if field_size <= 7:
            parts.append(
                f"With only {field_size} runners, one ordinary performance from a short-priced rival is enough to put this horse right into the finish."
            )
        parts.append(
            "The reasoning is deliberately cautious: prefer the horse whose card data still stands up when the favourite's price is treated with scepticism."
        )

    elif bot == "BloodlineBetty":
        parts.append(
            f"{name} is taken as a progressive or profile type based on the pattern in the published form and the race setup, not on unstated breeding claims."
        )
        parts.append(form_block)
        if trend >= 0.55 and form:
            parts.append(
                "The sequence of results is at least stable or improving into this race, which is the only 'improvement' claim that can be made from the card alone."
            )
        if cond_block:
            parts.append(cond_block)
        if surface == "AW":
            parts.append(
                "This is an all-weather surface; without a long personal history on the card, the point is simply that the trip and going figures available are not a clear negative."
            )
        if conn_block:
            parts.append(conn_block)
        parts.append(
            "The bet assumes that what is already visible in the figures and conditions is enough to support another solid effort, without inventing private improvement."
        )

    else:  # PaceProphet
        parts.append(
            f"{name} is the selection on race shape: field size, likely tempo and who is booked to ride, using only what the card shows."
        )
        if field_size >= 12:
            parts.append(
                f"There are {field_size} runners, so a horse that can travel into the race and find room matters as much as the pure form ranking."
            )
        elif field_size <= 5:
            parts.append(
                f"Only {field_size} are declared, so early position and a clean jump can matter more than a small form margin on paper."
            )
        else:
            parts.append(
                f"A field of {field_size} is large enough that a messy shape can toss out the pure form order."
            )
        if jockey:
            parts.append(
                f"{jockey} holds the ride"
                + (f" and has {j_day} mounts on the day" if j_day >= 2 else "")
                + ", which is relevant to how the horse is likely to be placed in the field."
            )
        parts.append(form_block)
        if cond_block:
            parts.append(cond_block)
        parts.append(
            "No claim is made about unseen sectionals; the point is that the card's field size, trip and booking give this horse a workable shape to run into."
        )

    # Bet type close
    if tip_type == "ew":
        parts.append(
            f"Recommendation: each-way {name} at around {odds:.2f}, using the place terms available in a field of {field_size}."
        )
    else:
        parts.append(
            f"Recommendation: win bet on {name} at around {odds:.2f}."
        )

    text = " ".join(p.strip() for p in parts if p and p.strip())
    text = " ".join(text.split())

    # Ensure minimum length using only real residual facts (no fiction)
    if _wc(text) < 50:
        extras = []
        if form and "form line" not in text.lower():
            extras.append(form_block)
        if conn_block and "Connections:" not in text:
            extras.append(conn_block)
        if cond_block and "Race conditions:" not in text:
            extras.append(cond_block)
        if rival_block and rival_block not in text:
            extras.append(rival_block)
        extras.append(
            f"All of the above is taken from today's racecard data for {name}"
            + (f" at {course}" if course else "")
            + "; nothing beyond those published fields is assumed."
        )
        text = " ".join([text] + extras)
        text = " ".join(text.split())

    return text



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
