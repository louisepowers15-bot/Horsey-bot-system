#!/usr/bin/env python3
"""
Generate tips from the 6 bots for a given day's racecards.

This version uses a lightweight, transparent scoring model so the bots
can still decide freely between win / E/W / longshot based on edge and confidence.

Usage:
  python generate_tips.py
  python generate_tips.py --date 2026-11-21
"""

import argparse
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
DATA_DIR.mkdir(exist_ok=True)

BOTS = {
    "BloodlineBetty": {"form": 0.25, "pedigree": 0.40, "trainer": 0.15, "value": 0.20},
    "DevilAdvocate":  {"form": 0.30, "pedigree": 0.10, "trainer": 0.20, "value": 0.40},
    "FormFox":        {"form": 0.55, "pedigree": 0.05, "trainer": 0.15, "value": 0.25},
    "HotTrainer":     {"form": 0.20, "pedigree": 0.10, "trainer": 0.50, "value": 0.20},
    "PaceProphet":    {"form": 0.30, "pedigree": 0.10, "trainer": 0.15, "value": 0.45},
    "ValueHunter":    {"form": 0.25, "pedigree": 0.10, "trainer": 0.15, "value": 0.50},
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def decide_type(prob: float, decimal_odds: float) -> tuple[str, int, str]:
    """Return (type, confidence, reason)"""
    implied = 1.0 / decimal_odds
    edge = prob - implied
    conf = int(round(prob * 100))

    if decimal_odds <= 2.5 and prob >= 0.45:
        return "win", min(conf, 85), "Strong favourite with high confidence"
    if decimal_odds >= 4.0 and edge > 0.05:
        return "ew", min(conf, 72), "Each-way value at the price"
    if decimal_odds >= 10 and edge > 0.08:
        return "win", min(conf, 55), "Big-priced runner with positive edge"
    return "win", max(35, min(conf, 78)), "Best option on the card" if edge > 0 else "Preferred selection"


def score_runner(bot_bias: dict, runner: dict) -> float:
    """Very simple transparent score. Replace with richer features later."""
    # Normalise available signals into 0-1
    form = runner.get("form_score", random.uniform(0.3, 0.8))
    pedigree = runner.get("pedigree_score", random.uniform(0.2, 0.7))
    trainer = runner.get("trainer_score", random.uniform(0.25, 0.75))
    value = runner.get("value_score", random.uniform(0.2, 0.8))

    s = (
        bot_bias["form"] * form +
        bot_bias["pedigree"] * pedigree +
        bot_bias["trainer"] * trainer +
        bot_bias["value"] * value
    )
    # Add a little noise so bots don't always agree
    s += random.uniform(-0.06, 0.06)
    return max(0.08, min(0.92, s))


def generate_from_sample(d: date) -> dict:
    """
    Generate a realistic tip set for the big meetings of the day.
    Used when we don't yet have a full scraped card.
    """
    # Hard-coded structure for 21 Nov 2026 style card (Betfair Chase day)
    sample_races = [
        {
            "course": "Haydock",
            "time": "15:00",
            "name": "Betfair Chase (Grade 1)",
            "runners": [
                {"name": "Grey Dawning", "odds": 3.5},
                {"name": "Ahoy Senor", "odds": 9.0},
                {"name": "Bravemansgame", "odds": 6.5},
                {"name": "Protektorat", "odds": 8.0},
                {"name": "Royale Pagaille", "odds": 12.0},
            ]
        },
        {
            "course": "Ascot",
            "time": "14:05",
            "name": "1965 Chase (Grade 2)",
            "runners": [
                {"name": "Jonbon", "odds": 1.8},
                {"name": "Edwardstone", "odds": 5.5},
                {"name": "Energumene", "odds": 7.0},
            ]
        },
        {
            "course": "Ascot",
            "time": "13:30",
            "name": "Ascot Hurdle (Grade 2)",
            "runners": [
                {"name": "Lossiemouth", "odds": 2.2},
                {"name": "Constitution Hill", "odds": 3.75},
                {"name": "State Man", "odds": 6.0},
            ]
        },
        {
            "course": "Haydock",
            "time": "13:15",
            "name": "Newton Novices' Hurdle (Grade 2)",
            "runners": [
                {"name": "North Shore", "odds": 3.5},
                {"name": "Cosmic Connection", "odds": 3.75},
                {"name": "Wilde's Legacy", "odds": 7.0},
            ]
        },
        {
            "course": "Punchestown",
            "time": "13:03",
            "name": "Florida Pearl Novice Chase",
            "runners": [
                {"name": "Ballygunner Castle", "odds": 3.25},
                {"name": "Kiss Will", "odds": 3.25},
                {"name": "Its Bilbo", "odds": 4.5},
            ]
        },
    ]

    races_out = []
    for race in sample_races:
        tips = []
        for bot_name, bias in BOTS.items():
            # Score every runner
            scored = []
            for r in race["runners"]:
                # Invent plausible feature scores for the prototype
                r2 = dict(r)
                r2["form_score"] = random.uniform(0.35, 0.85)
                r2["pedigree_score"] = random.uniform(0.25, 0.8)
                r2["trainer_score"] = random.uniform(0.3, 0.8)
                r2["value_score"] = max(0.1, 1.0 / r["odds"] + random.uniform(-0.15, 0.25))
                prob = score_runner(bias, r2)
                scored.append((prob, r2))

            scored.sort(key=lambda x: x[0], reverse=True)
            best_prob, best = scored[0]
            tip_type, conf, reason = decide_type(best_prob, best["odds"])

            tips.append({
                "bot": bot_name,
                "horse": best["name"],
                "odds": best["odds"],
                "conf": conf,
                "type": tip_type,
                "reason": reason,
                "stars": 1   # will be recalculated below
            })

        # Calculate agreement stars
        from collections import Counter
        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = min(4, counts[t["horse"]])

        # Sort tips by stars then confidence
        tips.sort(key=lambda t: (-t["stars"], -t["conf"]))
        races_out.append({
            "course": race["course"],
            "time": race["time"],
            "name": race["name"],
            "tips": tips
        })

    return {
        "date": d.isoformat(),
        "meetings": sorted({r["course"] for r in races_out}),
        "races": races_out,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Prototype tips using transparent scoring. Replace with richer model later."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    d = parse_date(args.date)

    print(f"Generating tips for {d.isoformat()}")

    # For now we always use the sample generator.
    # Once scrape_racecards.py produces good structured data we can switch.
    tips = generate_from_sample(d)

    out_path = DATA_DIR / f"tips-{d.isoformat()}.json"
    out_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Meetings: {', '.join(tips['meetings'])}")
    print(f"Races tipped: {len(tips['races'])}")


if __name__ == "__main__":
    main()
