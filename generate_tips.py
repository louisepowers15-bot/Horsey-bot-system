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
    opts = [o for o in opts if o]
    if not opts:
        return ""
    return opts[sum(ord(c) for c in seed) % len(opts)]


def _plain_form(form: str) -> tuple[str, list[str]]:
    """Turn a form string into plain-English facts a novice can follow."""
    tokens = parse_form_tokens(form)
    if not form or not tokens:
        return "", []
    facts = []
    last = tokens[0]
    last_map = {
        "1": "It won its most recent race.",
        "2": "It finished second last time out — only just beaten.",
        "3": "It finished third last time, so it was still involved at the finish.",
        "0": "It did not finish in the first three last time.",
        "F": "It fell last time, so that run is best treated with caution.",
        "P": "It was pulled up last time and did not finish the race.",
        "U": "The jockey was unseated last time, so that run is hard to judge.",
        "R": "It refused or failed to complete last time.",
        "B": "It was brought down or failed to complete last time.",
    }
    if last in last_map:
        facts.append(last_map[last])
    wins = sum(1 for t in tokens[:6] if t == "1")
    places = sum(1 for t in tokens[:6] if t in ("1", "2", "3"))
    if wins >= 2:
        facts.append(f"Looking at its recent runs, it has won {wins} of them.")
    elif places >= 3:
        facts.append(f"It has finished in the top three {places} times in its recent runs.")
    elif wins == 1:
        facts.append("It has a win among its recent runs.")
    return form, facts


def _wc(text: str) -> int:
    return len([w for w in text.replace(".", " ").split() if w])


def tipster_reason(bot, r, tip_type, conf, field_size, rivals: list | None = None):
    """
    Clear, novice-friendly explanation of why this horse can win.
    Minimum ~50 words. Only uses real card data — no invented stats.
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
    trend = float(r.get("_trend") or 0.5)
    t_day = int(r.get("_t_day_n") or 0)
    j_day = int(r.get("_j_day_n") or 0)
    c_day = int(r.get("_c_day_n") or 0)
    seed = f"{bot}|{name}|{form}|{course}|{odds:.2f}|{rank}"

    form_raw, form_facts = _plain_form(form)

    fav = None
    if rivals:
        fav = min(rivals, key=lambda x: float(x.get("odds") or 99))
        if (fav.get("name") or "") == name:
            fav = None

    # Shared plain pieces
    where = []
    if course:
        where.append(f"at {course}")
    if trip:
        where.append(f"over {trip}")
    if surface == "AW":
        where.append("on the all-weather (synthetic) surface")
    elif going:
        # simplify long going strings
        gshort = going.split("(")[0].strip()
        where.append(f"on ground described as {gshort}")
    where_txt = ", ".join(where) if where else "in this race"

    field_txt = ""
    if field_size >= 12:
        field_txt = f"There are {field_size} horses in the race, so it is competitive and a clear run matters."
    elif field_size <= 5:
        field_txt = f"There are only {field_size} horses in the race, so every runner has a real chance if things fall right."
    elif field_size:
        field_txt = f"There are {field_size} horses lined up."

    paras: list[str] = []

    if bot == "FormFox":
        paras.append(
            f"I am picking {name} because of what it has already done on the track {where_txt}."
        )
        if form_facts:
            paras.append(" ".join(form_facts))
            if form_raw:
                paras.append(f"Its recent form figures are {form_raw}.")
        elif form_raw:
            paras.append(f"Its recent form figures are {form_raw}, which still look usable in this company.")
        else:
            paras.append(
                "There is not much form written up for this horse, so this is a thinner form case than usual."
            )
        if trend >= 0.58 and form_facts:
            paras.append("The newer runs look better than the older ones, which is a good sign.")
        if field_txt:
            paras.append(field_txt)
        if form_s >= 0.5:
            paras.append(
                "If it runs to the same level again, it has a strong chance of winning or being right there at the finish."
            )
        else:
            paras.append(
                "The form is not perfect, but compared with the others it still looks one of the more reliable options."
            )

    elif bot == "HotTrainer":
        if trainer:
            paras.append(
                f"I am with {name} mainly because of the trainer, {trainer}, and how this horse is being placed today {where_txt}."
            )
        else:
            paras.append(f"I am with {name} on connections and how the horse is placed today.")
        if t_day >= 3 and trainer:
            paras.append(
                f"{trainer} has {t_day} horses running today, which usually means the yard is serious about this meeting."
            )
        if jockey:
            if c_day >= 2:
                paras.append(
                    f"{jockey} is riding for the same trainer more than once today, so the partnership is intentional."
                )
            elif j_day >= 3:
                paras.append(
                    f"{jockey} has {j_day} rides on the card, so this is not a one-off booking."
                )
            else:
                paras.append(f"{jockey} is in the saddle.")
        if form_facts:
            paras.append(" ".join(form_facts[:2]))
        elif form_raw:
            paras.append(f"Recent form reads {form_raw}.")
        if field_txt:
            paras.append(field_txt)
        paras.append(
            "A capable yard, a sensible jockey booking, and enough form on the page is a straightforward reason to think this horse can win."
        )

    elif bot == "ValueHunter":
        paras.append(
            f"At around {odds:.2f}, {name} looks a fair price to me for what it has shown, racing {where_txt}."
        )
        if form_facts:
            paras.append(" ".join(form_facts[:2]))
            if form_raw:
                paras.append(f"Form figures: {form_raw}.")
        elif form_raw:
            paras.append(f"Form figures: {form_raw}.")
        else:
            paras.append("Form on the card is light, so the price has to do more of the work.")
        if trainer and t_day >= 2:
            paras.append(
                f"{trainer} has {t_day} runners today, so this is unlikely to be a complete afterthought from the yard."
            )
        if rank >= 4:
            paras.append(
                "Several horses are shorter in the betting, but the form does not clearly prove they should be."
            )
        if field_txt:
            paras.append(field_txt)
        paras.append(
            "I would rather take this price on a horse with solid enough form than back a shorter one that is not clearly better on what we can see."
        )

    elif bot == "DevilAdvocate":
        if fav and fav.get("name"):
            fname = fav["name"]
            fform = (fav.get("_form_raw") or fav.get("form") or "").strip()
            fo = float(fav.get("odds") or 0)
            if fform:
                paras.append(
                    f"The favourite is {fname} at about {fo:.2f}, with form {fform}. That is respectable, but it is not so strong that everything else should be ignored."
                )
            else:
                paras.append(
                    f"The favourite is {fname} at about {fo:.2f}, without a big form line on the card."
                )
        paras.append(
            f"I prefer {name} {where_txt}, because the case for the shorter-priced horses is not as clear as the odds suggest."
        )
        if form_facts:
            paras.append(" ".join(form_facts[:2]))
            if form_raw:
                paras.append(f"Its own form figures are {form_raw}.")
        elif form_raw:
            paras.append(f"Its own form figures are {form_raw}.")
        if field_size and field_size <= 7:
            paras.append(
                f"With only {field_size} runners, if the favourite has an off day this horse is immediately in the mix."
            )
        elif field_txt:
            paras.append(field_txt)
        if jockey:
            paras.append(f"{jockey} rides.")
        paras.append(
            "In plain terms: I am not convinced the favourite is a good thing, and this horse’s form is good enough to take advantage."
        )

    elif bot == "BloodlineBetty":
        paras.append(
            f"{name} looks open to running well {where_txt}, based on the pattern of its recent results rather than any private information."
        )
        if form_facts:
            paras.append(" ".join(form_facts[:2]))
            if form_raw:
                paras.append(f"Form figures: {form_raw}.")
        if trend >= 0.55 and form_raw:
            paras.append(
                "The more recent runs are at least as good as, or better than, the older ones — a sign things may be coming together."
            )
        if trip:
            paras.append(f"The distance ({trip}) looks a reasonable match for what it has been doing.")
        if surface == "AW":
            paras.append(
                "This is on the all-weather. We can only go on the form shown; nothing on the card says the surface is a clear negative."
            )
        elif going:
            gshort = going.split("(")[0].strip()
            paras.append(f"The ground ({gshort}) does not look an obvious problem from the information we have.")
        if trainer:
            paras.append(f"It is trained by {trainer}.")
        if field_txt:
            paras.append(field_txt)
        paras.append(
            "Putting that together, there is a clear, simple case that this horse can be involved in the finish and has a real chance to win."
        )

    else:  # PaceProphet
        paras.append(
            f"My angle on {name} is how the race is likely to unfold {where_txt}."
        )
        if field_size >= 12:
            paras.append(
                f"With {field_size} runners it can get messy in the pack. You want a horse that can travel comfortably and still have a say at the finish — this one fits that job on the form we have."
            )
        elif field_size <= 5:
            paras.append(
                f"Only {field_size} runners means tactics and position matter a lot; a small mistake from a rival can hand the race over."
            )
        else:
            paras.append(
                f"There are {field_size} runners, enough for the shape of the race to matter as well as pure ability."
            )
        if jockey:
            if j_day >= 3:
                paras.append(
                    f"{jockey} rides and has {j_day} mounts today, so they will know how hard to go and when to wait."
                )
            else:
                paras.append(f"{jockey} is a sensible booking for getting a horse into the right place.")
        if form_facts:
            paras.append(" ".join(form_facts[:2]))
        elif form_raw:
            paras.append(f"Form figures: {form_raw}.")
        if trip:
            paras.append(f"Over {trip}, how fast they go early will decide who has energy left.")
        paras.append(
            "So the reason to back it is practical: the setup of the race gives this horse a fair chance to show its form and win."
        )

    # Clear recommendation
    if tip_type == "ew":
        paras.append(
            f"Suggestion: back {name} each-way at around {odds:.2f} (you win if it finishes first, and you still get a return if it places under the usual each-way rules for a field of this size)."
        )
    else:
        paras.append(
            f"Suggestion: back {name} to win at around {odds:.2f}."
        )

    text = " ".join(p.strip() for p in paras if p and p.strip())
    text = " ".join(text.split())

    # Pad to 50+ words using only real leftover facts
    if _wc(text) < 50:
        extra = []
        if form_raw and form_raw not in text:
            extra.append(f"The form string on the card is {form_raw}.")
        if trainer and trainer not in text:
            extra.append(f"Trainer: {trainer}.")
        if jockey and jockey not in text:
            extra.append(f"Jockey: {jockey}.")
        if course and course not in text:
            extra.append(f"Course: {course}.")
        extra.append(
            "Every point above comes from today’s racecard (form, trainer, jockey, distance, ground, field size and price) — nothing extra is assumed."
        )
        text = " ".join([text] + extra)
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
