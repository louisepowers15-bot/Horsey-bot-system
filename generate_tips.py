#!/usr/bin/env python3
"""
Generate tips from the 6 bots for a given day's scraped racecards.
Reads racecards-YYYY-MM-DD.json and writes tips-YYYY-MM-DD.json.
"""

import argparse
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent

BOTS = {
    "BloodlineBetty": {"form": 0.25, "pedigree": 0.40, "trainer": 0.15, "value": 0.20},
    "DevilAdvocate":  {"form": 0.25, "pedigree": 0.10, "trainer": 0.20, "value": 0.45},
    "FormFox":        {"form": 0.50, "pedigree": 0.10, "trainer": 0.15, "value": 0.25},
    "HotTrainer":     {"form": 0.20, "pedigree": 0.10, "trainer": 0.50, "value": 0.20},
    "PaceProphet":    {"form": 0.30, "pedigree": 0.10, "trainer": 0.20, "value": 0.40},
    "ValueHunter":    {"form": 0.20, "pedigree": 0.10, "trainer": 0.15, "value": 0.55},
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def score_runner(bot_bias: dict, runner: dict, rng: random.Random) -> float:
    odds = max(1.1, float(runner.get("odds") or 8.0))
    form = float(runner.get("form_score") or 0.4)
    pedigree = float(runner.get("pedigree_score") or 0.45)
    trainer = float(runner.get("trainer_score") or 0.4)
    value = float(runner.get("value_score") or min(0.7, 1.0 / odds + 0.15))

    s = (
        bot_bias["form"] * form +
        bot_bias["pedigree"] * pedigree +
        bot_bias["trainer"] * trainer +
        bot_bias["value"] * value
    )
    s += rng.uniform(-0.05, 0.05)
    return max(0.1, min(0.9, s))


def build_reason(bot_name: str, runner: dict, tip_type: str, conf: int, field_size: int) -> str:
    """Build a more detailed reason from available runner fields."""
    name = runner.get("name", "This horse")
    odds = float(runner.get("odds") or 0)
    form = str(runner.get("form") or "").strip()
    jockey = (runner.get("jockey") or "").strip()
    trainer = (runner.get("trainer") or "").strip()
    form_score = float(runner.get("form_score") or 0)
    trainer_score = float(runner.get("trainer_score") or 0)

    parts = []

    # Form
    if form:
        parts.append(f"Recent form figures read {form}.")
    if form_score >= 0.55:
        parts.append("The form score is solid relative to this field.")
    elif form_score > 0 and form_score < 0.4:
        parts.append("Form is not the strongest on paper, so other angles matter more here.")

    # Trainer / jockey
    if trainer:
        if trainer_score >= 0.5:
            parts.append(f"{trainer}'s runners are respected in this type of race.")
        else:
            parts.append(f"Trained by {trainer}.")
    if jockey:
        parts.append(f"{jockey} takes the ride.")

    # Odds / type
    if tip_type == "ew":
        parts.append(
            f"At around {odds:.1f} this looks a realistic each-way chance rather than a pure win play — "
            f"the price gives room if the market leaders underperform."
        )
        if field_size and field_size < 5:
            parts.append("Field is small, so place terms may be tight — still taken as an each-way view on ability.")
    else:
        if odds and odds <= 2.5:
            parts.append(f"Short enough at {odds:.2f} to be treated as a win selection if the form holds up.")
        elif odds and odds >= 8:
            parts.append(f"Bigger price ({odds:.1f}) but the profile is interesting enough for a win interest.")
        else:
            parts.append(f"Preferred win option at around {odds:.2f}.")

    # Bot flavour
    if bot_name == "FormFox":
        parts.append("FormFox weights recent performance heavily in this assessment.")
    elif bot_name == "HotTrainer":
        parts.append("HotTrainer puts extra emphasis on yard form and connections.")
    elif bot_name == "ValueHunter":
        parts.append("ValueHunter is focused on whether the price still offers an edge.")
    elif bot_name == "DevilAdvocate":
        parts.append("DevilAdvocate is looking for alternatives to the obvious favourite.")
    elif bot_name == "BloodlineBetty":
        parts.append("BloodlineBetty factors pedigree and longer-term potential into the view.")
    elif bot_name == "PaceProphet":
        parts.append("PaceProphet is mindful of how the race is likely to be run.")

    parts.append(f"Confidence marked at {conf}%.")
    return " ".join(parts)


def decide_type_and_conf(prob: float, decimal_odds: float, field_size: int) -> tuple:
    decimal_odds = max(1.1, float(decimal_odds or 8.0))
    conf = int(round(prob * 100))
    conf = max(30, min(conf, 88))

    # E/W only when field and price make sense
    if field_size >= 8 and decimal_odds >= 7.0 and prob >= 0.28:
        return "ew", min(conf, 70)
    if 5 <= field_size <= 7 and decimal_odds >= 6.0 and prob >= 0.30:
        return "ew", min(conf, 68)
    if decimal_odds <= 2.8 and prob >= 0.42:
        return "win", min(conf, 85)
    return "win", conf


def build_tips_for_races(d: date, flat_races: list) -> dict:
    races_out = []
    meetings = sorted({r.get("course") or "Unknown" for r in flat_races})

    for idx, race in enumerate(flat_races):
        runners = [r for r in (race.get("runners") or []) if r.get("name")]
        if not runners:
            continue

        field_size = len(runners)
        tips = []
        # Stable but different RNG per race so tips vary
        rng = random.Random(f"{d.isoformat()}-{race.get('course')}-{race.get('time')}-{idx}")

        for bot_name, bias in BOTS.items():
            scored = []
            for runner in runners:
                prob = score_runner(bias, runner, rng)
                scored.append((prob, runner))
            scored.sort(key=lambda x: x[0], reverse=True)
            best_prob, best_runner = scored[0]

            tip_type, conf = decide_type_and_conf(best_prob, best_runner.get("odds") or 8.0, field_size)
            reason = build_reason(bot_name, best_runner, tip_type, conf, field_size)

            tips.append({
                "bot": bot_name,
                "horse": best_runner["name"],
                "odds": round(float(best_runner.get("odds") or 8.0), 2),
                "conf": conf,
                "type": tip_type,
                "reason": reason,
            })

        # Stars = how many bots picked the same horse
        counts = {}
        for t in tips:
            counts[t["horse"]] = counts.get(t["horse"], 0) + 1
        for t in tips:
            t["stars"] = counts[t["horse"]]

        races_out.append({
            "course": race.get("course") or "Unknown",
            "time": race.get("time") or "",
            "name": race.get("name") or "",
            "tips": tips,
        })

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Generated from scraped racecards",
    }


def load_scraped_races(d: date) -> list:
    rc_path = DATA_DIR / f"racecards-{d.isoformat()}.json"
    if not rc_path.exists():
        print(f"No racecards file: {rc_path}")
        return []
    try:
        data = json.loads(rc_path.read_text(encoding="utf-8"))
        flat = []
        for m in data.get("meetings") or []:
            course = m.get("course") or "Unknown"
            for r in m.get("races") or []:
                runners = r.get("runners") or []
                if not runners:
                    continue
                flat.append({
                    "course": course,
                    "time": r.get("time") or "",
                    "name": r.get("name") or "",
                    "runners": runners,
                })
        return flat
    except Exception as e:
        print(f"Error reading {rc_path}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    d = parse_date(args.date)

    print(f"Generating tips for {d.isoformat()}")
    scraped = load_scraped_races(d)

    if scraped:
        tips = build_tips_for_races(d, scraped)
    else:
        print("Warning: No scraped runners found for this date.")
        tips = {
            "date": d.isoformat(),
            "meetings": [],
            "races": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": "No scraped racecards available.",
        }

    out_path = DATA_DIR / f"tips-{d.isoformat()}.json"
    out_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Meetings: {', '.join(tips.get('meetings') or [])}")
    print(f"Races tipped: {len(tips.get('races') or [])}")
    # quick diversity check
    horses = set()
    for r in tips.get("races") or []:
        for t in r.get("tips") or []:
            horses.add(t.get("horse"))
    print(f"Unique horses tipped: {len(horses)}")


if __name__ == "__main__":
    main()
