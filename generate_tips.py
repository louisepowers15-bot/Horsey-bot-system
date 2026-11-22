#!/usr/bin/env python3
"""
Generate tips from 6 bots. Each bot freely chooses win/E/W/longshot
and writes its own distinct reasoning (form, trainer, ground angles, price, field).
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

SOFT_LEAN = {
    "BloodlineBetty": {"form": 0.28, "pedigree": 0.32, "trainer": 0.18, "value": 0.22},
    "DevilAdvocate":  {"form": 0.28, "pedigree": 0.12, "trainer": 0.22, "value": 0.38},
    "FormFox":        {"form": 0.42, "pedigree": 0.12, "trainer": 0.18, "value": 0.28},
    "HotTrainer":     {"form": 0.22, "pedigree": 0.12, "trainer": 0.42, "value": 0.24},
    "PaceProphet":    {"form": 0.30, "pedigree": 0.12, "trainer": 0.22, "value": 0.36},
    "ValueHunter":    {"form": 0.22, "pedigree": 0.12, "trainer": 0.18, "value": 0.48},
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
        + rng.uniform(-0.08, 0.08)
    )
    return max(0.12, min(0.9, s))


def choose_type(prob: float, odds: float, field_size: int, rng: random.Random) -> str:
    odds = max(1.15, float(odds or 10.0))
    if field_size >= 8 and odds >= 7.0 and prob >= 0.26 and rng.random() < 0.55:
        return "ew"
    if 5 <= field_size <= 7 and odds >= 6.5 and prob >= 0.28 and rng.random() < 0.45:
        return "ew"
    return "win"


def reason_formfox(runner, tip_type, conf, field_size, odds):
    form = str(runner.get("form") or "").strip() or "limited recent figures"
    bits = [
        f"The form book is the main driver here. Recent figures read {form}.",
    ]
    fs = float(runner.get("form_score") or 0)
    if fs >= 0.55:
        bits.append("That level of form is strong enough in this company to take a positive view.")
    elif fs < 0.4:
        bits.append("The figures aren’t sparkling, but relative to this field they still put this horse in the mix.")
    else:
        bits.append("Solid enough form to be interested without needing to invent a story.")
    if field_size and field_size <= 6:
        bits.append(f"Only {field_size} runners — a weaker or thinner field can make ordinary form look better on the day.")
    if tip_type == "ew":
        bits.append(f"At around {odds:.1f} I’m happier each-way than forcing a win-only case.")
    else:
        bits.append(f"Taking it to win at about {odds:.2f} on the form edge.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def reason_hottrainer(runner, tip_type, conf, field_size, odds):
    trainer = (runner.get("trainer") or "this yard").strip()
    jockey = (runner.get("jockey") or "").strip()
    ts = float(runner.get("trainer_score") or 0)
    bits = [f"Starting from the connections. {trainer} is the angle I’m prioritising."]
    if ts >= 0.5:
        bits.append("Yard stats for this sort of race are a genuine positive.")
    else:
        bits.append("Not the hottest yard on the numbers, but still a trainer I won’t ignore when the price is right.")
    if jockey:
        bits.append(f"{jockey} keeps the ride — that continuity matters.")
    form = str(runner.get("form") or "").strip()
    if form:
        bits.append(f"Form figures ({form}) don’t argue against the yard view.")
    if tip_type == "ew":
        bits.append(f"Price around {odds:.1f} suits an each-way stance while the trainer angle plays out.")
    else:
        bits.append(f"Win selection at about {odds:.2f} on the strength of the yard/horse combination.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def reason_valuehunter(runner, tip_type, conf, field_size, odds):
    bits = [f"Price is the filter. Offered around {odds:.2f}."]
    fs = float(runner.get("form_score") or 0)
    if odds >= 8:
        bits.append("That’s a big enough price that only a realistic chance of hitting the frame (or better) is needed to be interested.")
    elif odds <= 2.5:
        bits.append("Short, so there has to be a clear edge on chance vs price — I’m only here if the profile backs it up.")
    else:
        bits.append("Mid-range price; need the chance to look a bit better than the market implies.")
    if fs >= 0.5:
        bits.append("Form score supports taking that price.")
    form = str(runner.get("form") or "").strip()
    if form:
        bits.append(f"Recent runs ({form}) are part of that calculation.")
    if tip_type == "ew":
        bits.append("Each-way is the sensible way to play the edge without over-committing to a win.")
    else:
        bits.append("Happy to take it win-only at this number.")
    if field_size and field_size >= 10:
        bits.append(f"Field of {field_size} helps the each-way math if you’re in that market.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def reason_devil(runner, tip_type, conf, field_size, odds):
    bits = [
        "Not automatically following the tightest price in the market.",
        f"This selection is the alternative that still makes sense on the data at about {odds:.2f}.",
    ]
    form = str(runner.get("form") or "").strip()
    if form:
        bits.append(f"Form line {form} is usable even if it isn’t the flashiest in the race.")
    trainer = (runner.get("trainer") or "").strip()
    if trainer:
        bits.append(f"{trainer}’s runner is entitled to be in the argument.")
    if field_size and field_size <= 7:
        bits.append(f"Smallish field ({field_size}) — one or two underperformances change the result quickly.")
    if tip_type == "ew":
        bits.append("Each-way protects the case if the favourite proves solid but this one still places.")
    else:
        bits.append("Taking it to win as the best non-obvious option.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def reason_betty(runner, tip_type, conf, field_size, odds):
    bits = [
        "Looking at the longer-term profile as much as the last run.",
    ]
    form = str(runner.get("form") or "").strip()
    if form:
        bits.append(f"Recent form ({form}) is the short-term check; pedigree and progression sit behind that.")
    ps = float(runner.get("pedigree_score") or 0.45)
    if ps >= 0.5:
        bits.append("Breeding/profile scores well enough to stay interested beyond pure last-day form.")
    trainer = (runner.get("trainer") or "").strip()
    if trainer:
        bits.append(f"In the care of {trainer}, which fits a progressive or well-bred type.")
    if tip_type == "ew":
        bits.append(f"At {odds:.1f} an each-way view matches a horse that may still be improving into the race.")
    else:
        bits.append(f"Win play at about {odds:.2f} on profile plus current form.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


def reason_pace(runner, tip_type, conf, field_size, odds):
    bits = [
        "Interested in how this race is likely to be run, not only the bare ratings.",
    ]
    if field_size:
        if field_size <= 6:
            bits.append(f"With only {field_size} runners, position and tempo matter more than a big-field scramble.")
        else:
            bits.append(f"Field of {field_size} — need a horse that can obtain a clear run or dictate if required.")
    form = str(runner.get("form") or "").strip()
    if form:
        bits.append(f"Form figures {form} suggest this one can cope with a true or tactical race.")
    jockey = (runner.get("jockey") or "").strip()
    if jockey:
        bits.append(f"{jockey} is a plus for race management.")
    if tip_type == "ew":
        bits.append(f"Price near {odds:.1f} makes each-way the practical expression of that view.")
    else:
        bits.append(f"Win selection around {odds:.2f} if the race unfolds as expected.")
    bits.append(f"Confidence {conf}%.")
    return " ".join(bits)


REASONERS = {
    "FormFox": reason_formfox,
    "HotTrainer": reason_hottrainer,
    "ValueHunter": reason_valuehunter,
    "DevilAdvocate": reason_devil,
    "BloodlineBetty": reason_betty,
    "PaceProphet": reason_pace,
}


def build_reason(bot: str, runner: dict, tip_type: str, conf: int, field_size: int) -> str:
    odds = float(runner.get("odds") or 0)
    fn = REASONERS.get(bot, reason_formfox)
    return fn(runner, tip_type, conf, field_size, odds)


def build_chat(races_out: list, d: date) -> list:
    tally = {}
    for race in races_out:
        for t in race.get("tips") or []:
            key = (t["horse"], race.get("course"), race.get("time"))
            if key not in tally:
                tally[key] = {
                    "horse": t["horse"], "course": race.get("course"), "time": race.get("time"),
                    "odds": t.get("odds"), "type": t.get("type"), "bots": [], "conf": 0,
                }
            tally[key]["bots"].append(t["bot"])
            tally[key]["conf"] += t.get("conf") or 0
    ranked = sorted(tally.values(), key=lambda x: (len(x["bots"]), x["conf"]), reverse=True)
    top = ranked[:8]
    chat = []
    if not top:
        chat.append({"bot": "FormFox", "text": "Not enough solid data today to force multiples."})
        return chat
    h0 = top[0]
    chat.append({"bot": "FormFox", "text": f"Clearest agreement for me is {h0['horse']} ({h0['course']} {h0['time']}) — {len(h0['bots'])} bots aligned."})
    chat.append({"bot": "ValueHunter", "text": f"That one’s about {h0.get('odds')}. Fine as an anchor; I still want a longer-priced leg in any double."})
    if len(top) > 1:
        h1 = top[1]
        chat.append({"bot": "DevilAdvocate", "text": f"I’d pair it with {h1['horse']} at {h1.get('odds')} rather than stacking two short ones."})
    chat.append({"bot": "HotTrainer", "text": "As long as the yard angle doesn’t fight the form, short leg + one each-way type is fine."})
    chat.append({"bot": "PaceProphet", "text": "Don’t build a six-fold where every leg needs a perfect trip in a big field."})
    chat.append({"bot": "BloodlineBetty", "text": "Agreed — main money on the strong singles/doubles; tiny stakes only on long accas."})

    def fmt(legs):
        return " + ".join(f"{x['horse']} ({x['course']} {x['time']})" for x in legs) if legs else "—"

    win_legs = [x for x in top if x.get("type") != "ew"][:3] or top[:3]
    ew_legs = [x for x in top if x.get("type") == "ew"][:3]
    mixed = top[:6]
    chat.append({"bot": "FormFox", "text": f"Winners double proposal: {fmt(win_legs[:2])}."})
    chat.append({"bot": "ValueHunter", "text": f"Each-way double idea: {fmt(ew_legs[:2] if len(ew_legs) >= 2 else mixed[:2])}."})
    chat.append({"bot": "DevilAdvocate", "text": f"Fun 6-fold only, tiny stake: {fmt(mixed)}."})
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

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "chat": build_chat(races_out, d),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Distinct per-bot reasoning; free win/E/W choice",
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
            "date": d.isoformat(), "meetings": [], "races": [], "chat": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": "No scraped racecards available.",
        }
    out_path = DATA_DIR / f"tips-{d.isoformat()}.json"
    out_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Races tipped: {len(tips.get('races') or [])}")
    if tips.get("races"):
        sample = tips["races"][0]["tips"][0]
        print("Sample reason:", sample["bot"], "→", sample["reason"][:120], "...")


if __name__ == "__main__":
    main()
