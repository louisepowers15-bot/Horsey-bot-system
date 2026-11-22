#!/usr/bin/env python3
"""
Generate tips from 6 neutral bots. Each bot scores every runner independently
and freely chooses win / E/W / longshot — no fixed style is forced.
Styles will emerge later from recorded results.
"""

import argparse
import json
import random
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

# Soft lean only — not hard locks. Small random noise so they diverge naturally.
SOFT_LEAN = {
    "BloodlineBetty": {"form": 0.28, "pedigree": 0.32, "trainer": 0.18, "value": 0.22},
    "DevilAdvocate":  {"form": 0.28, "pedigree": 0.12, "trainer": 0.22, "value": 0.38},
    "FormFox":        {"form": 0.40, "pedigree": 0.12, "trainer": 0.20, "value": 0.28},
    "HotTrainer":     {"form": 0.24, "pedigree": 0.12, "trainer": 0.40, "value": 0.24},
    "PaceProphet":    {"form": 0.30, "pedigree": 0.12, "trainer": 0.22, "value": 0.36},
    "ValueHunter":    {"form": 0.24, "pedigree": 0.12, "trainer": 0.18, "value": 0.46},
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def score_runner(bot: str, runner: dict, rng: random.Random) -> float:
    lean = SOFT_LEAN.get(bot, {"form": 0.3, "pedigree": 0.2, "trainer": 0.25, "value": 0.25})
    odds = max(1.15, float(runner.get("odds") or 10.0))
    form = float(runner.get("form_score") or 0.4)
    pedigree = float(runner.get("pedigree_score") or 0.45)
    trainer = float(runner.get("trainer_score") or 0.4)
    value = float(runner.get("value_score") or min(0.75, 0.12 + 1.0 / odds))

    s = (
        lean["form"] * form
        + lean["pedigree"] * pedigree
        + lean["trainer"] * trainer
        + lean["value"] * value
    )
    # Natural divergence — each bot “sees” the race slightly differently
    s += rng.uniform(-0.08, 0.08)
    return max(0.12, min(0.9, s))


def choose_type(prob: float, odds: float, field_size: int, rng: random.Random) -> str:
    """Free choice: win or E/W based on price + field, not bot identity."""
    odds = max(1.15, float(odds or 10.0))
    # Longshot / value E/W when price is big enough and field supports place terms
    if field_size >= 8 and odds >= 7.0 and prob >= 0.26 and rng.random() < 0.55:
        return "ew"
    if 5 <= field_size <= 7 and odds >= 6.5 and prob >= 0.28 and rng.random() < 0.45:
        return "ew"
    # Short or mid-price → usually win
    return "win"


def build_reason(bot: str, runner: dict, tip_type: str, conf: int, field_size: int) -> str:
    name = runner.get("name", "This horse")
    odds = float(runner.get("odds") or 0)
    form = str(runner.get("form") or "").strip()
    jockey = (runner.get("jockey") or "").strip()
    trainer = (runner.get("trainer") or "").strip()
    form_score = float(runner.get("form_score") or 0)
    trainer_score = float(runner.get("trainer_score") or 0)

    bits = []

    if form:
        bits.append(f"Form figures: {form}.")
    if form_score >= 0.55:
        bits.append("Recent form looks competitive in this company.")
    elif 0 < form_score < 0.4:
        bits.append("Form is ordinary on the figures — other factors are carrying the case.")

    if trainer:
        if trainer_score >= 0.5:
            bits.append(f"{trainer} is a positive in races of this type.")
        else:
            bits.append(f"Trained by {trainer}.")
    if jockey:
        bits.append(f"Jockey: {jockey}.")

    if tip_type == "ew":
        bits.append(
            f"At about {odds:.1f} this is taken each-way — enough price to be interested "
            f"if the principals underperform, without needing to force a win-only view."
        )
    else:
        if odds <= 2.6:
            bits.append(f"Short enough ({odds:.2f}) to treat as a win selection if the profile holds.")
        elif odds >= 9:
            bits.append(
                f"Bigger price ({odds:.1f}) but the combination of form/connections is enough "
                f"to prefer it for a win interest rather than only the place."
            )
        else:
            bits.append(f"Preferred as a win at around {odds:.2f}.")

    # Light personality colour without locking behaviour
    if bot == "FormFox":
        bits.append("Reading leans on the form book.")
    elif bot == "HotTrainer":
        bits.append("Yard/connections angle is weighted in this view.")
    elif bot == "ValueHunter":
        bits.append("Price vs chance is the main filter here.")
    elif bot == "DevilAdvocate":
        bits.append("Looking past the most obvious market horse where the data allows.")
    elif bot == "BloodlineBetty":
        bits.append("Longer-term profile and breeding context factored in.")
    elif bot == "PaceProphet":
        bits.append("How the race may unfold is part of the assessment.")

    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def build_chat(races_out: list, d: date) -> list:
    """
    Simple bot chat: they surface strong consensus horses and settle on
    a shared double / treble / 6-fold. Distinct voices, shared conclusion.
    """
    # Aggregate agreement
    tally = {}
    for race in races_out:
        for t in race.get("tips") or []:
            key = (t["horse"], race.get("course"), race.get("time"), t.get("odds"), t.get("type"))
            if key not in tally:
                tally[key] = {"horse": t["horse"], "course": race.get("course"), "time": race.get("time"),
                              "odds": t.get("odds"), "type": t.get("type"), "bots": [], "conf": 0}
            tally[key]["bots"].append(t["bot"])
            tally[key]["conf"] += t.get("conf") or 0

    ranked = sorted(tally.values(), key=lambda x: (len(x["bots"]), x["conf"]), reverse=True)
    top = ranked[:8] if ranked else []

    chat = []
    if not top:
        chat.append({"bot": "FormFox", "text": "Thin card or incomplete data today — not forcing multiples."})
        return chat

    h0 = top[0]
    chat.append({
        "bot": "FormFox",
        "text": f"Strongest agreement I’m seeing is {h0['horse']} ({h0['course']} {h0['time']}) — {len(h0['bots'])} of us onside."
    })
    chat.append({
        "bot": "ValueHunter",
        "text": f"Price on that one is about {h0.get('odds')}. Fine as an anchor if we build a double, but I want at least one longer leg."
    })
    if len(top) > 1:
        h1 = top[1]
        chat.append({
            "bot": "DevilAdvocate",
            "text": f"I’d rather not just rubber-stamp the favourite cluster. {h1['horse']} at {h1.get('odds')} is the one I’d pair for a bit of value."
        })
    chat.append({
        "bot": "HotTrainer",
        "text": "As long as the yard angle isn’t fighting the form, I’m fine with a short-priced leg plus one each-way type."
    })
    chat.append({
        "bot": "PaceProphet",
        "text": "Race shape matters on the big-field handicaps — don’t load six legs that all need a perfect trip."
    })
    chat.append({
        "bot": "BloodlineBetty",
        "text": "I’m happy to go with the group double if we’re honest about confidence and not stacking six thin opinions."
    })

    # Collective picks
    win_legs = [x for x in top if x.get("type") != "ew"][:3]
    ew_legs = [x for x in top if x.get("type") == "ew"][:3]
    mixed = top[:6]

    def fmt(legs):
        return " + ".join(f"{x['horse']} ({x['course']} {x['time']})" for x in legs) if legs else "—"

    chat.append({
        "bot": "FormFox",
        "text": f"Proposed winners double: {fmt(win_legs[:2])}."
    })
    chat.append({
        "bot": "ValueHunter",
        "text": f"Each-way double idea: {fmt(ew_legs[:2] if len(ew_legs) >= 2 else mixed[:2])}."
    })
    chat.append({
        "bot": "DevilAdvocate",
        "text": f"If we’re doing a 6-fold for fun, keep stakes tiny: {fmt(mixed)}."
    })
    chat.append({
        "bot": "HotTrainer",
        "text": "Agreed — small stakes on the long accas. Main focus stays the single and double where agreement is highest."
    })
    return chat


def build_tips_for_races(d: date, flat_races: list) -> dict:
    races_out = []
    meetings = sorted({r.get("course") or "Unknown" for r in flat_races})

    for idx, race in enumerate(flat_races):
        runners = [r for r in (race.get("runners") or []) if r.get("name")]
        if not runners:
            continue

        field_size = len(runners)
        tips = []
        rng = random.Random(f"{d.isoformat()}|{race.get('course')}|{race.get('time')}|{idx}")

        for bot in BOT_NAMES:
            scored = [(score_runner(bot, r, rng), r) for r in runners]
            scored.sort(key=lambda x: x[0], reverse=True)
            prob, best = scored[0]
            odds = float(best.get("odds") or 10.0)
            tip_type = choose_type(prob, odds, field_size, rng)
            conf = max(32, min(88, int(round(prob * 100))))
            tips.append({
                "bot": bot,
                "horse": best["name"],
                "odds": round(odds, 2),
                "conf": conf,
                "type": tip_type,
                "reason": build_reason(bot, best, tip_type, conf, field_size),
            })

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

    chat = build_chat(races_out, d)

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "chat": chat,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Free-choice tips; styles emerge from results over time",
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
            "chat": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": "No scraped racecards available.",
        }

    out_path = DATA_DIR / f"tips-{d.isoformat()}.json"
    out_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Meetings: {', '.join(tips.get('meetings') or [])}")
    print(f"Races tipped: {len(tips.get('races') or [])}")
    horses = {t.get("horse") for r in tips.get("races") or [] for t in r.get("tips") or []}
    print(f"Unique horses tipped: {len(horses)}")
    print(f"Chat lines: {len(tips.get('chat') or [])}")


if __name__ == "__main__":
    main()
