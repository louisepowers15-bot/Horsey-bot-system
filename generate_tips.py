#!/usr/bin/env python3
"""
Free multi-bot tip generator.
- Each bot scores runners with different weights and free win/E/W choice.
- Distinct, data-driven reasons per bot.
- Chat room = real vote on doubles / trebles / 6-folds from their tips.
"""

import argparse
import json
import random
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

# Soft leans only — free choice of horse and win/E/W
SOFT_LEAN = {
    "BloodlineBetty": {"form": 0.28, "pedigree": 0.32, "trainer": 0.18, "value": 0.22},
    "DevilAdvocate":  {"form": 0.28, "pedigree": 0.12, "trainer": 0.22, "value": 0.38},
    "FormFox":        {"form": 0.44, "pedigree": 0.10, "trainer": 0.18, "value": 0.28},
    "HotTrainer":     {"form": 0.22, "pedigree": 0.10, "trainer": 0.44, "value": 0.24},
    "PaceProphet":    {"form": 0.30, "pedigree": 0.12, "trainer": 0.22, "value": 0.36},
    "ValueHunter":    {"form": 0.20, "pedigree": 0.10, "trainer": 0.18, "value": 0.52},
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def score_runner(bot: str, runner: dict, rng: random.Random) -> float:
    lean = SOFT_LEAN[bot]
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
        + rng.uniform(-0.07, 0.07)
    )
    return max(0.12, min(0.9, s))


def choose_type(prob: float, odds: float, field_size: int, rng: random.Random) -> str:
    odds = max(1.15, float(odds or 10.0))
    if field_size >= 8 and odds >= 7.0 and prob >= 0.26 and rng.random() < 0.55:
        return "ew"
    if 5 <= field_size <= 7 and odds >= 6.5 and prob >= 0.28 and rng.random() < 0.4:
        return "ew"
    return "win"


# ---------- Distinct reasons ----------

def _base_facts(runner, field_size, odds):
    form = str(runner.get("form") or "").strip()
    trainer = (runner.get("trainer") or "").strip()
    jockey = (runner.get("jockey") or "").strip()
    fs = float(runner.get("form_score") or 0)
    ts = float(runner.get("trainer_score") or 0)
    return form, trainer, jockey, fs, ts, field_size, odds


def reason_formfox(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = []
    if form:
        lines.append(f"Form figures {form} are the main reason for this pick.")
    else:
        lines.append("Limited form in the book, so this is a relative call against the rest of the field.")
    if fs >= 0.55:
        lines.append("That level of form looks competitive here.")
    elif fs and fs < 0.4:
        lines.append("Figures are modest, but they still stand up better than several rivals.")
    if field_size and field_size <= 6:
        lines.append(f"Only {field_size} runners — thinner fields can upgrade ordinary form.")
    if tip_type == "ew":
        lines.append(f"At about {odds:.1f} this is an each-way view, not a forced win.")
    else:
        lines.append(f"Taking it to win around {odds:.2f} on the form edge.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def reason_hottrainer(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = []
    if trainer:
        lines.append(f"Connections first: {trainer} is the angle.")
    else:
        lines.append("Yard/connections are carrying this selection.")
    if ts >= 0.5:
        lines.append("Trainer profile for this type of race is a clear positive.")
    elif trainer:
        lines.append("Not the strongest yard numbers, but still preferred to several alternatives.")
    if jockey:
        lines.append(f"{jockey} stays on — useful continuity.")
    if form:
        lines.append(f"Form ({form}) does not argue against the yard view.")
    if tip_type == "ew":
        lines.append(f"Price near {odds:.1f} suits each-way while that trainer angle plays out.")
    else:
        lines.append(f"Win selection at about {odds:.2f}.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def reason_valuehunter(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = [f"Price first: about {odds:.2f}."]
    if odds >= 9:
        lines.append("Big enough that a realistic place (or better) chance is enough to be interested.")
    elif odds <= 2.4:
        lines.append("Short — only interested if the chance clearly beats the price.")
    else:
        lines.append("Need the chance to look a bit better than the market implies.")
    if form:
        lines.append(f"Form line {form} is part of that price-vs-chance check.")
    if fs >= 0.5:
        lines.append("Form score supports taking the number.")
    if tip_type == "ew":
        lines.append("Each-way is the practical way to take the edge.")
        if field_size and field_size >= 8:
            lines.append(f"Field of {field_size} helps the place side of the bet.")
    else:
        lines.append("Win-only at this price.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def reason_devil(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = [
        "Not defaulting to the tightest price in the market.",
        f"This is the alternative that still stacks up at around {odds:.2f}.",
    ]
    if form:
        lines.append(f"Form {form} is usable even if it is not the flashiest.")
    if trainer:
        lines.append(f"{trainer}'s runner belongs in the argument.")
    if field_size and field_size <= 7:
        lines.append(f"Small field ({field_size}) — one underperformance from a favourite changes everything.")
    if tip_type == "ew":
        lines.append("Each-way covers the case if the favourite holds but this one still places.")
    else:
        lines.append("Win interest as the best non-obvious option.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def reason_betty(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = ["Looking past the last run alone — profile and progression matter."]
    if form:
        lines.append(f"Recent form ({form}) is the short-term check.")
    ps = float(runner.get("pedigree_score") or 0.45)
    if ps >= 0.5:
        lines.append("Longer-term profile scores well enough to stay interested.")
    if trainer:
        lines.append(f"With {trainer}, that profile is in the right hands.")
    if tip_type == "ew":
        lines.append(f"At {odds:.1f} each-way fits a horse that may still be improving.")
    else:
        lines.append(f"Win play around {odds:.2f} on profile plus current form.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def reason_pace(runner, tip_type, conf, field_size, odds):
    form, trainer, jockey, fs, ts, field_size, odds = _base_facts(runner, field_size, odds)
    lines = ["How the race is likely to be run matters as much as the bare figures."]
    if field_size:
        if field_size <= 6:
            lines.append(f"Only {field_size} runners — position and tempo matter more than a big-field scramble.")
        else:
            lines.append(f"Field of {field_size}: needs a horse that can get a run or help dictate.")
    if form:
        lines.append(f"Form {form} suggests this one can cope with a true or tactical pace.")
    if jockey:
        lines.append(f"{jockey} is a plus for race placement.")
    if tip_type == "ew":
        lines.append(f"Around {odds:.1f} — each-way is the practical expression of that view.")
    else:
        lines.append(f"Win selection near {odds:.2f} if the race unfolds as expected.")
    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


REASONERS = {
    "FormFox": reason_formfox,
    "HotTrainer": reason_hottrainer,
    "ValueHunter": reason_valuehunter,
    "DevilAdvocate": reason_devil,
    "BloodlineBetty": reason_betty,
    "PaceProphet": reason_pace,
}


def build_reason(bot, runner, tip_type, conf, field_size):
    odds = float(runner.get("odds") or 0)
    return REASONERS[bot](runner, tip_type, conf, field_size, odds)


# ---------- Real vote-based chat ----------

def leg_key(course, time, horse):
    return f"{horse} ({course} {time})"


def build_vote_chat(races_out):
    """
    Each bot nominates legs from its own tips.
    We tally votes for double / treble / 6-fold candidates and write a short discussion.
    """
    # Per-bot ranked candidates: prefer higher conf, mix win + ew
    bot_legs = {b: [] for b in BOT_NAMES}
    for race in races_out:
        course, time = race.get("course"), race.get("time")
        for t in race.get("tips") or []:
            bot_legs[t["bot"]].append({
                "bot": t["bot"],
                "horse": t["horse"],
                "course": course,
                "time": time,
                "odds": t.get("odds"),
                "conf": t.get("conf") or 0,
                "type": t.get("type") or "win",
                "label": leg_key(course, time, t["horse"]),
            })

    for b in BOT_NAMES:
        bot_legs[b].sort(key=lambda x: (-x["conf"], x["odds"] or 99))
        # unique horses
        seen = set()
        uniq = []
        for leg in bot_legs[b]:
            if leg["horse"] in seen:
                continue
            seen.add(leg["horse"])
            uniq.append(leg)
        bot_legs[b] = uniq

    # Each bot votes: top 2 as double candidates, top 3 treble, top 6 for sixfold
    double_votes = Counter()
    treble_votes = Counter()
    six_votes = Counter()
    nominations = {b: {"double": [], "treble": [], "six": []} for b in BOT_NAMES}

    for b in BOT_NAMES:
        legs = bot_legs[b]
        if not legs:
            continue
        d_legs = legs[:2]
        t_legs = legs[:3]
        s_legs = legs[:6]
        nominations[b]["double"] = [x["label"] for x in d_legs]
        nominations[b]["treble"] = [x["label"] for x in t_legs]
        nominations[b]["six"] = [x["label"] for x in s_legs]
        for x in d_legs:
            double_votes[x["label"]] += 1
        for x in t_legs:
            treble_votes[x["label"]] += 1
        for x in s_legs:
            six_votes[x["label"]] += 1

    def top_n(counter, n):
        return [lab for lab, _ in counter.most_common(n)]

    voted_double = top_n(double_votes, 2)
    voted_treble = top_n(treble_votes, 3)
    voted_six = top_n(six_votes, 6)

    chat = []
    # Opening — bots state a preferred leg
    for b in BOT_NAMES:
        legs = bot_legs[b]
        if not legs:
            continue
        top = legs[0]
        style = "each-way" if top["type"] == "ew" else "win"
        chat.append({
            "bot": b,
            "text": f"My strongest single is {top['label']} as a {style} (conf {top['conf']}%, about {top['odds']}).",
        })

    # Disagreement / support on doubles
    if voted_double:
        chat.append({
            "bot": "FormFox",
            "text": f"For a winners double I’m voting: {' + '.join(voted_double)}. That’s where our top votes cluster.",
        })
    # Show a bot that might disagree
    for b in ["DevilAdvocate", "ValueHunter"]:
        alt = nominations[b]["double"]
        if alt and alt != voted_double:
            chat.append({
                "bot": b,
                "text": f"I’d rather go {' + '.join(alt)} — different balance of price and confidence from my card.",
            })
            break

    chat.append({
        "bot": "HotTrainer",
        "text": "Happy to follow the vote if the yard angles on those legs aren’t fighting the form.",
    })
    chat.append({
        "bot": "PaceProphet",
        "text": "Keep the 6-fold tiny. Big fields need clean trips — don’t treat six legs like six bankers.",
    })

    if voted_treble:
        chat.append({
            "bot": "BloodlineBetty",
            "text": f"Treble vote result: {' + '.join(voted_treble)}.",
        })
    if voted_six:
        chat.append({
            "bot": "ValueHunter",
            "text": f"6-fold (fun only): {' + '.join(voted_six)}. Stake small.",
        })

    # Final tally summary as system-style line from FormFox
    chat.append({
        "bot": "FormFox",
        "text": (
            "Vote locked. "
            f"Double: {' + '.join(voted_double) or '—'}. "
            f"Treble: {' + '.join(voted_treble) or '—'}. "
            f"6-fold: {' + '.join(voted_six) or '—'}."
        ),
    })

    return {
        "chat": chat,
        "votes": {
            "double": voted_double,
            "treble": voted_treble,
            "sixfold": voted_six,
            "double_tally": dict(double_votes.most_common(8)),
            "treble_tally": dict(treble_votes.most_common(10)),
        },
    }


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

        counts = Counter(t["horse"] for t in tips)
        for t in tips:
            t["stars"] = counts[t["horse"]]

        races_out.append({
            "course": race.get("course") or "Unknown",
            "time": race.get("time") or "",
            "name": race.get("name") or "",
            "tips": tips,
        })

    vote_block = build_vote_chat(races_out)

    return {
        "date": d.isoformat(),
        "meetings": meetings,
        "races": races_out,
        "chat": vote_block["chat"],
        "votes": vote_block["votes"],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Free bots with distinct reasons + real vote on multiples",
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
        print("Warning: No scraped runners found.")
        tips = {
            "date": d.isoformat(), "meetings": [], "races": [], "chat": [], "votes": {},
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": "No scraped racecards available.",
        }
    out = DATA_DIR / f"tips-{d.isoformat()}.json"
    out.write_text(json.dumps(tips, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Races: {len(tips.get('races') or [])}")
    print(f"Chat lines: {len(tips.get('chat') or [])}")
    if tips.get("votes"):
        print("Voted double:", tips["votes"].get("double"))
    if tips.get("races"):
        t0 = tips["races"][0]["tips"][0]
        print("Sample:", t0["bot"], "→", t0["reason"][:100], "...")


if __name__ == "__main__":
    main()
