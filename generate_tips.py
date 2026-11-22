#!/usr/bin/env python3
"""
Free multi-bot tips with tipster-style reasons and disciplined outsider control.
"""

import argparse
import json
import random
import re
from collections import Counter
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
    "FormFox":        {"form": 0.32, "trend": 0.10, "trainer": 0.12, "jockey": 0.10, "combo": 0.08, "value": 0.12, "field": 0.08, "going": 0.04, "trip": 0.04},
    "HotTrainer":     {"form": 0.16, "trend": 0.08, "trainer": 0.26, "jockey": 0.12, "combo": 0.14, "value": 0.10, "field": 0.06, "going": 0.04, "trip": 0.04},
    "ValueHunter":    {"form": 0.16, "trend": 0.08, "trainer": 0.10, "jockey": 0.08, "combo": 0.08, "value": 0.28, "field": 0.10, "going": 0.06, "trip": 0.06},
    "DevilAdvocate":  {"form": 0.20, "trend": 0.08, "trainer": 0.12, "jockey": 0.10, "combo": 0.10, "value": 0.18, "field": 0.10, "going": 0.06, "trip": 0.06},
    "BloodlineBetty": {"form": 0.18, "trend": 0.12, "trainer": 0.14, "jockey": 0.10, "combo": 0.12, "value": 0.12, "field": 0.08, "going": 0.06, "trip": 0.08},
    "PaceProphet":    {"form": 0.18, "trend": 0.08, "trainer": 0.12, "jockey": 0.14, "combo": 0.12, "value": 0.12, "field": 0.14, "going": 0.05, "trip": 0.05},
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
            score -= 0.07 * w  # recent fails hurt more
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


def enrich(runner, field_size, all_odds, going, distance):
    r = dict(runner)
    odds = max(1.15, float(r.get("odds") or 10.0))
    r["odds"] = odds
    fscore, trend = form_metrics(str(r.get("form") or ""))
    if r.get("form_score"):
        fscore = max(fscore, float(r["form_score"]) * 0.75)
    r["_form"] = fscore
    r["_trend"] = trend
    r["_trainer"] = float(r.get("trainer_score") or (0.55 if r.get("trainer") else 0.4))
    r["_jockey"] = float(r.get("jockey_score") or (0.53 if r.get("jockey") else 0.4))
    r["_combo"] = min(0.8, (r["_jockey"] + r["_trainer"]) / 2 + 0.08) if (r.get("jockey") and r.get("trainer")) else 0.4

    implied = 1.0 / odds
    edge = r["_form"] - implied
    r["_value"] = max(0.08, min(0.85, 0.42 + edge * 0.85))
    # long odds need serious form to keep value
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

    g = (going or "").lower()
    r["_going"] = 0.51 if g else 0.5
    r["_trip"] = 0.51 if distance else 0.5
    r["_going_txt"] = going or ""
    r["_trip_txt"] = distance or ""
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
    # Favourites with solid form get a small boost (don't auto-oppose)
    if r["_rank"] <= 2 and r["_form"] >= 0.5:
        s += 0.045
    if r["_rank"] == 1 and r["_form"] >= 0.55:
        s += 0.03
    # Outsiders need elite form
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
    s += rng.uniform(-0.03, 0.03)
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
    """ranked = list of (score, runner). Avoid weak big-priced pile-ups."""
    for prob, r in ranked:
        if r["odds"] >= 16 and r["_form"] < 0.55:
            continue
        if r["odds"] >= 20 and r["_rank"] >= 4 and r["_form"] < 0.6:
            continue
        tip_type = choose_type(bot, r, field_size, prob)
        return prob, r, tip_type
    # fallback: best score among top half of market if possible
    market = [x for x in ranked if x[1]["_rank"] <= max(3, field_size // 2)]
    pool = market or ranked
    prob, r = pool[0]
    return prob, r, choose_type(bot, r, field_size, prob)


def tipster_reason(bot, r, tip_type, conf, field_size):
    """Racing-tipster prose only. No scoring jargon."""
    name = r.get("name") or "This horse"
    odds = r["odds"]
    form = str(r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    going = (r.get("_going_txt") or "").strip()
    trip = (r.get("_trip_txt") or "").strip()
    rank = r.get("_rank") or 0
    form_s = r.get("_form") or 0.4
    trend = r.get("_trend") or 0.5

    # Plain-English form note
    tokens = parse_form_tokens(form)
    form_bit = ""
    if tokens:
        if tokens[0] == "1":
            form_bit = "comes here off a win"
        elif tokens[0] == "2":
            form_bit = "was only just denied last time"
        elif tokens[0] == "3":
            form_bit = "ran a solid third last time"
        elif tokens[0] in ("F", "P", "U"):
            form_bit = "has a blot on the recent record but is better than that suggests"
        else:
            form_bit = f"recent figures read {form}"
        if any(t == "1" for t in tokens[1:4]):
            form_bit += " and has already shown the ability to win in this sort of grade"

    ground_trip = []
    if trip:
        ground_trip.append(f"over {trip}")
    if going:
        ground_trip.append(f"on {going}")
    gt = (" " + " ".join(ground_trip)) if ground_trip else ""

    # Bot flavour in tipster voice
    if bot == "FormFox":
        lead = f"{name} is the pick on form{gt}."
        if form_bit:
            mid = form_bit[0].upper() + form_bit[1:] + "."
        else:
            mid = "There is not a deep book of form in this race, and this one still stacks up best of those that have shown something."
        if form_s >= 0.55:
            mid += " The level already shown is good enough to dominate a race like this."
        elif trend >= 0.55:
            mid += " The direction of travel is positive, which matters as much as any single figure."
        else:
            mid += " Others may have more glamour, but few have actually achieved more on the track."
    elif bot == "HotTrainer":
        if trainer:
            lead = f"{name} is the one for {trainer}{gt}."
        else:
            lead = f"{name} is the yard pick in this line-up{gt}."
        mid = ""
        if jockey:
            mid += f"{jockey} retains the ride, which is a help. "
        if form_bit:
            mid += form_bit[0].upper() + form_bit[1:] + ". "
        mid += "When this team means business in this grade, they are worth siding with."
    elif bot == "ValueHunter":
        lead = f"{name} looks the value at around {odds:.2f}{gt}."
        mid = ""
        if form_bit:
            mid += form_bit[0].upper() + form_bit[1:] + ". "
        if odds >= 8:
            mid += "That price overstates the risks relative to what has already been shown. "
        elif odds <= 2.5:
            mid += "It is a short enough price, so there has to be a clear chance of winning — and there is. "
        else:
            mid += "The market has left just enough juice to make this interesting. "
        if tip_type == "ew":
            mid += "Each-way is the sensible way to play it."
        else:
            mid += "Happy enough taking it to win at the price."
    elif bot == "DevilAdvocate":
        if rank <= 2:
            lead = f"It is hard to oppose {name} if you strip the race back to basics{gt}."
        else:
            lead = f"{name} is preferred to the more obvious names{gt}."
        mid = ""
        if form_bit:
            mid += form_bit[0].upper() + form_bit[1:] + ". "
        mid += "A few of the shorter ones are open to attack on what they have actually done, and this profile holds up better under scrutiny."
        if field_size <= 7:
            mid += " With so few runners, one dull effort from a favourite puts this right in the mix."
    elif bot == "BloodlineBetty":
        lead = f"{name} has more about the profile than most of these{gt}."
        mid = ""
        if form_bit:
            mid += form_bit[0].upper() + form_bit[1:] + ". "
        if trainer:
            mid += f"In the care of {trainer}, there is every chance of a step forward. "
        else:
            mid += "There is still improvement to come on the balance of the evidence. "
        mid += "That progressive angle is enough to take a stand."
    else:  # PaceProphet
        lead = f"{name} should be suited by how this is likely to be run{gt}."
        mid = ""
        if field_size <= 6:
            mid += f"Only {field_size} runners, so it becomes a race about position as much as raw ability. "
        else:
            mid += f"In a field of {field_size} you need a horse that can find a gap when the sprint starts. "
        if jockey:
            mid += f"{jockey} is a positive for race placement. "
        if form_bit:
            mid += form_bit[0].upper() + form_bit[1:] + "."

    # Closing: win / EW in plain English
    if tip_type == "ew":
        close = f"Take {name} each-way at around {odds:.2f}."
    else:
        if rank <= 2 and odds <= 3.5:
            close = f"Back {name} to win — at about {odds:.2f} there is no need to look beyond this one."
        elif odds >= 12:
            close = f"A speculative win bet on {name} at around {odds:.2f} is justified only because the alternatives are thin."
        else:
            close = f"Back {name} to win at around {odds:.2f}."

    parts = [lead, mid.strip(), close]
    return " ".join(p for p in parts if p)


def build_tips_for_races(d, flat_races):
    races_out = []
    meetings = sorted({r.get("course") or "Unknown" for r in flat_races})

    for idx, race in enumerate(flat_races):
        raw = [x for x in (race.get("runners") or []) if x.get("name")]
        if not raw:
            continue
        field_size = len(raw)
        all_odds = [max(1.15, float(x.get("odds") or 10)) for x in raw]
        going = race.get("going") or ""
        distance = race.get("distance") or ""
        runners = [enrich(x, field_size, all_odds, going, distance) for x in raw]
        rng = random.Random(f"{d.isoformat()}|{race.get('course')}|{race.get('time')}|{idx}")

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
                "reason": tipster_reason(bot, best, tip_type, conf, field_size),
            })

        # If 5+ bots landed on the same 15+ outsider, force diversity for lower-conf bots
        counts = Counter(t["horse"] for t in tips)
        for horse, n in list(counts.items()):
            sample = next(t for t in tips if t["horse"] == horse)
            if n >= 5 and sample["odds"] >= 15:
                # re-pick for bots with lowest conf
                ordered = sorted([t for t in tips if t["horse"] == horse], key=lambda t: t["conf"])
                for t in ordered[: max(1, n - 3)]:
                    bot = t["bot"]
                    ranked = sorted(((score_bot(bot, r, rng), r) for r in runners), key=lambda x: -x[0])
                    # take best not equal to the outsider pile
                    for prob, r in ranked:
                        if r["name"] == horse:
                            continue
                        if r["odds"] >= 20 and r["_form"] < 0.55:
                            continue
                        t["horse"] = r["name"]
                        t["odds"] = round(r["odds"], 2)
                        t["type"] = choose_type(bot, r, field_size, prob)
                        t["conf"] = max(40, min(84, int(round(prob * 100))))
                        t["reason"] = tipster_reason(bot, r, t["type"], t["conf"], field_size)
                        break

        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = counts[t["horse"]]

        races_out.append({
            "course": race.get("course") or "Unknown",
            "time": race.get("time") or "",
            "name": race.get("name") or "",
            "going": going,
            "distance": distance,
            "tips": tips,
        })

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "tipster reasons + outsider discipline",
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


if __name__ == "__main__":
    main()
