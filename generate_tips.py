#!/usr/bin/env python3
"""
Generate tips from the 6 bots for a given day's scraped racecards.
Reads racecards-YYYY-MM-DD.json and writes tips-YYYY-MM-DD.json.
"""

import argparse
import json
import random
from collections import Counter
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
    decimal_odds = max(1.1, float(decimal_odds or 5.0))
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
    """Score a runner using form, pedigree, trainer, and value signals."""
    odds = max(1.1, float(runner.get("odds") or 5.0))
    form = runner.get("form_score", random.uniform(0.35, 0.80))
    pedigree = runner.get("pedigree_score", random.uniform(0.30, 0.75))
    trainer = runner.get("trainer_score", random.uniform(0.30, 0.75))
    value = runner.get("value_score", max(0.1, min(0.85, (1.0 / odds) + random.uniform(-0.1, 0.2))))

    s = (
        bot_bias["form"] * form +
        bot_bias["pedigree"] * pedigree +
        bot_bias["trainer"] * trainer +
        bot_bias["value"] * value
    )
    s += random.uniform(-0.06, 0.06)
    return max(0.08, min(0.92, s))


def build_tips_for_races(d: date, flat_races: list, source_note: str) -> dict:
    races_out = []
    for race in flat_races:
        runners = race.get("runners", [])
        if not runners:
            continue

        tips = []
        for bot_name, bias in BOTS.items():
            scored = []
            for r in runners:
                prob = score_runner(bias, r)
                scored.append((prob, r))

            scored.sort(key=lambda x: x[0], reverse=True)
            best_prob, best = scored[0]
            odds_val = float(best.get("odds") or 5.0)
            tip_type, conf, reason = decide_type(best_prob, odds_val)

            tips.append({
                "bot": bot_name,
                "horse": best["name"],
                "odds": odds_val,
                "conf": conf,
                "type": tip_type,
                "reason": reason,
                "stars": 1
            })

        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = min(4, counts[t["horse"]])

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
        "note": source_note
    }


def load_scraped_races(d: date) -> list:
    rc_path = DATA_DIR / f"racecards-{d.isoformat()}.json"
    if not rc_path.exists():
        return []
    try:
        data = json.loads(rc_path.read_text(encoding="utf-8"))
        flat = []
        for m in data.get("meetings", []):
            course = m.get("course", "Unknown")
            for r in m.get("races", []):
                if r.get("runners"):
                    flat.append({
                        "course": course,
                        "time": r.get("time", ""),
                        "name": r.get("name", ""),
                        "runners": r["runners"]
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
    scraped_races = load_scraped_races(d)

    if scraped_races:
        tips = build_tips_for_races(d, scraped_races, "Live scraped UK & Ireland racecards")
    else:
        print("Warning: No scraped runners found for this date.")
        tips = {
            "date": d.isoformat(),
            "meetings": [],
            "races": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": "No scraped racecards available."
        }

    out_path = DATA_DIR / f"tips-{d.isoformat()}.json"
    out_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Meetings: {', '.join(tips['meetings'])}")
    print(f"Races tipped: {len(tips['races'])}")


if __name__ == "__main__":
    main()
