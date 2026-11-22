#!/usr/bin/env python3
"""
Free multi-bot horse racing tips — stronger multi-factor model.

Every bot evaluates:
  form quality, recent trajectory, trainer, jockey, jockey-trainer combo,
  market rank / price value, field size, going, distance (when known).

Goals: fewer silly E/Ws, less random longshot spam, clearer reasons,
slightly more disciplined favourites when the card supports them.
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

# All bots use all factors; weights only tilt
WEIGHTS = {
    "FormFox":        {"form": 0.30, "trend": 0.10, "trainer": 0.12, "jockey": 0.10, "combo": 0.08, "value": 0.14, "field": 0.08, "going": 0.04, "trip": 0.04},
    "HotTrainer":     {"form": 0.16, "trend": 0.08, "trainer": 0.24, "jockey": 0.12, "combo": 0.14, "value": 0.10, "field": 0.08, "going": 0.04, "trip": 0.04},
    "ValueHunter":    {"form": 0.14, "trend": 0.08, "trainer": 0.08, "jockey": 0.08, "combo": 0.08, "value": 0.30, "field": 0.12, "going": 0.06, "trip": 0.06},
    "DevilAdvocate":  {"form": 0.18, "trend": 0.08, "trainer": 0.10, "jockey": 0.10, "combo": 0.10, "value": 0.20, "field": 0.12, "going": 0.06, "trip": 0.06},
    "BloodlineBetty": {"form": 0.18, "trend": 0.12, "trainer": 0.12, "jockey": 0.10, "combo": 0.12, "value": 0.12, "field": 0.10, "going": 0.06, "trip": 0.08},
    "PaceProphet":    {"form": 0.16, "trend": 0.08, "trainer": 0.10, "jockey": 0.14, "combo": 0.12, "value": 0.12, "field": 0.16, "going": 0.06, "trip": 0.06},
}


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def parse_form_tokens(form: str):
    """Return list of recent results newest-first where possible."""
    if not form:
        return []
    s = str(form).strip().upper().replace("-", " ").replace("/", " ")
    tokens = re.findall(r"[1-9]|0|F|P|U|R|B|C|S", s)
    return tokens[:8]


def form_metrics(form: str):
    tokens = parse_form_tokens(form)
    if not tokens:
        return 0.40, 0.50, "limited form on the card"
    score = 0.32
    places = 0
    wins = 0
    fails = 0
    for i, t in enumerate(tokens[:6]):
        w = 1.0 - i * 0.09
        if t == "1":
            score += 0.14 * w
            wins += 1
            places += 1
        elif t == "2":
            score += 0.09 * w
            places += 1
        elif t == "3":
            score += 0.06 * w
            places += 1
        elif t in ("4", "5"):
            score += 0.03 * w
        elif t in ("F", "P", "U", "R", "B"):
            score -= 0.05 * w
            fails += 1
        elif t == "0":
            score -= 0.02 * w
    score = max(0.18, min(0.92, score))
    # trend: recent half vs older half
    def half_score(chunk):
        if not chunk:
            return 0.45
        sc = 0.4
        for t in chunk:
            if t == "1":
                sc += 0.12
            elif t in ("2", "3"):
                sc += 0.06
            elif t in ("F", "P", "U"):
                sc -= 0.06
        return max(0.2, min(0.9, sc))
    recent = half_score(tokens[:3])
    older = half_score(tokens[3:6])
    trend = max(0.2, min(0.9, 0.5 + (recent - older) * 0.8))
    note = f"form {''.join(tokens[:6])}"
    if wins:
        note += f", {wins} recent win(s)"
    if fails:
        note += f", {fails} recent fail(s) coded"
    return score, trend, note


def enrich(runner, field_size, all_odds, going, distance):
    r = dict(runner)
    odds = max(1.15, float(r.get("odds") or 10.0))
    r["odds"] = odds
    fscore, trend, fnote = form_metrics(str(r.get("form") or ""))
    if r.get("form_score"):
        fscore = max(fscore, float(r["form_score"]) * 0.8)
    r["_form"] = fscore
    r["_trend"] = trend
    r["_form_note"] = fnote
    r["_trainer"] = float(r.get("trainer_score") or (0.57 if r.get("trainer") else 0.4))
    r["_jockey"] = float(r.get("jockey_score") or (0.55 if r.get("jockey") else 0.4))
    if r.get("jockey") and r.get("trainer"):
        r["_combo"] = min(0.82, (r["_jockey"] + r["_trainer"]) / 2 + 0.1)
    else:
        r["_combo"] = 0.4

    implied = 1.0 / odds
    # value: reward edge of form vs implied chance; punish random huge prices with weak form
    edge = r["_form"] - implied
    r["_value"] = max(0.1, min(0.9, 0.45 + edge * 0.9 + (0.06 if 4.5 <= odds <= 12 else 0)))
    if odds > 25 and r["_form"] < 0.45:
        r["_value"] *= 0.7

    # field: big fields help mid-price contenders; tiny fields need quality
    if field_size >= 11 and 5 <= odds <= 14:
        r["_field"] = 0.66
    elif field_size <= 4:
        r["_field"] = 0.58 if r["_form"] >= 0.5 else 0.36
    elif field_size <= 6 and odds <= 3.5:
        r["_field"] = 0.6
    else:
        r["_field"] = 0.5

    g = (going or "").lower()
    r["_going"] = 0.52 if g else 0.5
    if "heavy" in g or "soft" in g:
        r["_going"] = 0.49
    if "firm" in g:
        r["_going"] = 0.52
    r["_trip"] = 0.52 if distance else 0.5
    r["_going_txt"] = going or ""
    r["_trip_txt"] = distance or ""

    sorted_odds = sorted(all_odds)
    try:
        r["_rank"] = sorted_odds.index(odds) + 1
    except ValueError:
        r["_rank"] = max(1, len(sorted_odds) // 2)
    r["_n"] = field_size
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
    # Discipline tweaks
    if r["_rank"] == 1 and r["_form"] >= 0.55:
        s += 0.03  # don't be afraid of a solid favourite
    if bot == "DevilAdvocate" and r["_rank"] == 1 and r["_form"] < 0.58:
        s -= 0.07
    if bot == "ValueHunter" and r["odds"] < 2.1:
        s -= 0.06
    if r["odds"] > 34 and r["_form"] < 0.5:
        s -= 0.08  # cut hopeless outsiders
    s += rng.uniform(-0.035, 0.035)
    return max(0.1, min(0.94, s))


def choose_type(bot, r, field_size, prob):
    odds = r["odds"]
    if field_size < 5:
        return "win"
    if odds < 5.0:
        return "win"
    # need real form to go E/W
    if r["_form"] < 0.42:
        return "win"
    if field_size >= 8 and odds >= 7.0 and prob >= 0.30:
        return "ew"
    if field_size >= 7 and odds >= 8.0 and bot in ("ValueHunter", "DevilAdvocate") and prob >= 0.28:
        return "ew"
    return "win"


def build_reason(bot, r, tip_type, conf, field_size, rivals_note):
    odds = r["odds"]
    form = str(r.get("form") or "").strip()
    trainer = (r.get("trainer") or "").strip()
    jockey = (r.get("jockey") or "").strip()
    going = r.get("_going_txt") or ""
    trip = r.get("_trip_txt") or ""

    # Rank which internal scores drove the pick
    parts = [
        ("form", r["_form"]),
        ("recent trajectory", r["_trend"]),
        ("trainer", r["_trainer"]),
        ("jockey", r["_jockey"]),
        ("jockey–trainer combo", r["_combo"]),
        ("price vs chance", r["_value"]),
        ("field size fit", r["_field"]),
    ]
    parts.sort(key=lambda x: -x[1])
    a, b, c = parts[0][0], parts[1][0], parts[2][0]

    lines = []
    lines.append(
        f"{bot} scored the whole card (form, trajectory, trainer, jockey, combo, price, field"
        + (", going" if going else "")
        + (", trip" if trip else "")
        + f"). Top signals: {a}, {b}, then {c}."
    )

    detail = []
    if form:
        detail.append(r["_form_note"])
    if trainer:
        detail.append(f"trainer {trainer}")
    if jockey:
        detail.append(f"jockey {jockey}")
    if trainer and jockey:
        detail.append("combo present")
    if trip:
        detail.append(f"trip {trip}")
    if going:
        detail.append(f"going {going}")
    detail.append(f"{field_size} runners")
    detail.append(f"market rank {r['_rank']}")
    detail.append(f"odds {odds:.2f}")
    lines.append("Card facts: " + "; ".join(detail) + ".")

    if rivals_note:
        lines.append(rivals_note)

    if tip_type == "ew":
        lines.append(
            f"Each-way: price {odds:.2f} and field size support a place dimension; form is not pure guesswork."
        )
    else:
        if r["_rank"] == 1 and r["_form"] >= 0.55:
            lines.append(
                f"Win: solid favourite profile — form and connections justify taking {odds:.2f} to win rather than forcing a fancy."
            )
        elif odds >= 10:
            lines.append(
                f"Win at a bigger price ({odds:.2f}) only because combined signals still beat weaker rivals on this card."
            )
        else:
            lines.append(f"Win selection at about {odds:.2f} on the combined model, not a single angle.")

    lines.append(f"Confidence {conf}%.")
    return " ".join(lines)


def rivals_summary(best, runners):
    """Short note on why this horse screens ahead of the field."""
    others = [x for x in runners if x.get("name") != best.get("name")]
    if not others:
        return ""
    # compare form to median
    forms = sorted(x["_form"] for x in runners)
    med = forms[len(forms) // 2]
    if best["_form"] >= med + 0.08:
        return "Form screens above the median of this field."
    if best["_rank"] == 1:
        return "Clearest on the market; model agrees enough not to oppose blindly."
    if best["_value"] >= 0.58:
        return "Price still looks acceptable relative to the model chance."
    return "Edges the field on the combined score rather than one headline factor."


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
            prob, best = ranked[0]
            # if top is a weak outsider, consider second if much more solid
            if best["odds"] > 20 and best["_form"] < 0.48 and len(ranked) > 1:
                p2, r2 = ranked[1]
                if r2["_form"] >= best["_form"] + 0.08:
                    prob, best = p2, r2

            tip_type = choose_type(bot, best, field_size, prob)
            conf = max(38, min(86, int(round(prob * 100))))
            note = rivals_summary(best, runners)
            tips.append({
                "bot": bot,
                "horse": best["name"],
                "odds": round(best["odds"], 2),
                "conf": conf,
                "type": tip_type,
                "reason": build_reason(bot, best, tip_type, conf, field_size, note),
            })

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
        "note": "multi-factor disciplined free model",
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
    print(f"Generating disciplined free tips for {d.isoformat()}")
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
