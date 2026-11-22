#!/usr/bin/env python3
"""
Match tips to results and update leaderboard.json

Settlement rules (level £1 stake):
  WIN tip:  win  -> return = odds; else 0
  E/W tip:  stake split 0.5 win + 0.5 place
            place terms by field size: >=12 -> 1/4 odds 3 places;
            >=8 -> 1/5 odds 3 places; >=5 -> 1/4 odds 2 places; else win-only treatment
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOTS = [
    "BloodlineBetty", "DevilAdvocate", "FormFox",
    "HotTrainer", "PaceProphet", "ValueHunter",
]


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "yesterday":
        return date.today() - timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def norm(name: str) -> str:
    return " ".join(str(name or "").lower().replace(".", "").split())


def place_terms(field_size: int):
    """Return (place_fraction, places) or None if no EW."""
    if field_size >= 12:
        return 0.25, 3
    if field_size >= 8:
        return 0.20, 3
    if field_size >= 5:
        return 0.25, 2
    return None


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def result_index(results: dict):
    """Map (course_lower, time, horse_norm) -> position, and course+horse fallbacks."""
    by_ct_h = {}
    by_c_h = {}
    by_h = {}
    field_by_ct = {}
    for m in results.get("meetings") or []:
        for race in m.get("races") or []:
            course = (race.get("course") or m.get("course") or "").strip()
            time = (race.get("time") or "").strip()
            field = race.get("field_size") or len(race.get("runners") or [])
            field_by_ct[(course.lower(), time)] = field
            for ru in race.get("runners") or []:
                h = norm(ru.get("name"))
                pos = ru.get("position")
                by_ct_h[(course.lower(), time, h)] = pos
                by_c_h[(course.lower(), h)] = pos
                by_h[h] = pos
    return by_ct_h, by_c_h, by_h, field_by_ct


def settle_tip(tip, pos, field_size):
    """Return dict with outcome, stake, return."""
    odds = float(tip.get("odds") or 0) or 0
    ttype = (tip.get("type") or "win").lower()
    stake = 1.0
    if pos is None:
        return {"outcome": "unknown", "stake": 0.0, "return": 0.0, "pnl": 0.0}

    if ttype != "ew":
        won = pos == 1
        ret = odds if won else 0.0
        return {
            "outcome": "win" if won else "lose",
            "stake": stake,
            "return": ret,
            "pnl": ret - stake,
            "position": pos,
        }

    terms = place_terms(field_size or 0)
    if not terms:
        # treat as win-only if no EW terms
        won = pos == 1
        ret = odds if won else 0.0
        return {
            "outcome": "win" if won else "lose",
            "stake": stake,
            "return": ret,
            "pnl": ret - stake,
            "position": pos,
        }

    frac, places = terms
    win_stake = 0.5
    place_stake = 0.5
    win_ret = (odds * win_stake) if pos == 1 else 0.0
    place_odds = 1.0 + (odds - 1.0) * frac
    place_ret = (place_odds * place_stake) if pos is not None and pos <= places else 0.0
    total = win_ret + place_ret
    if pos == 1:
        outcome = "win"
    elif pos <= places:
        outcome = "place"
    else:
        outcome = "lose"
    return {
        "outcome": outcome,
        "stake": stake,
        "return": total,
        "pnl": total - stake,
        "position": pos,
        "place_terms": f"{frac} odds, {places} places",
    }


def empty_bot():
    return {
        "tips": 0, "wins": 0, "places": 0, "losses": 0, "unknown": 0,
        "stakes": 0.0, "returns": 0.0, "pnl": 0.0,
        "avg_odds": 0.0, "_odds_sum": 0.0,
        "style": {"win": 0, "ew": 0},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="yesterday")
    args = p.parse_args()
    d = parse_date(args.date)
    ds = d.isoformat()

    tips = load_json(ROOT / f"tips-{ds}.json")
    results = load_json(ROOT / f"results-{ds}.json")
    if not tips:
        print(f"No tips file for {ds}")
        return
    if not results:
        print(f"No results file for {ds} — run scrape_results.py first")
        return

    by_ct_h, by_c_h, by_h, field_by_ct = result_index(results)
    lb_path = ROOT / "leaderboard.json"
    lb = load_json(lb_path) or {
        "updated_at": None,
        "bots": {b: empty_bot() for b in BOTS},
        "history": [],
    }
    for b in BOTS:
        if b not in lb["bots"]:
            lb["bots"][b] = empty_bot()

    settled_races = []
    day_summary = {"date": ds, "tips": 0, "settled": 0, "pnl": 0.0}

    for race in tips.get("races") or []:
        course = race.get("course") or ""
        time = race.get("time") or ""
        field = field_by_ct.get((course.lower(), time))
        if not field:
            # estimate from tips context later
            field = 8
        stips = []
        for tip in race.get("tips") or []:
            h = norm(tip.get("horse"))
            pos = by_ct_h.get((course.lower(), time, h))
            if pos is None:
                pos = by_c_h.get((course.lower(), h))
            if pos is None:
                pos = by_h.get(h)
            settlement = settle_tip(tip, pos, field)
            row = {**tip, **settlement, "course": course, "time": time, "race": race.get("name")}
            stips.append(row)
            day_summary["tips"] += 1

            bot = tip.get("bot")
            if bot not in lb["bots"]:
                lb["bots"][bot] = empty_bot()
            b = lb["bots"][bot]
            if settlement["outcome"] == "unknown":
                b["unknown"] += 1
                continue
            day_summary["settled"] += 1
            day_summary["pnl"] += settlement["pnl"]
            b["tips"] += 1
            b["stakes"] += settlement["stake"]
            b["returns"] += settlement["return"]
            b["pnl"] += settlement["pnl"]
            b["_odds_sum"] += float(tip.get("odds") or 0)
            b["avg_odds"] = round(b["_odds_sum"] / max(1, b["tips"]), 2)
            ttype = (tip.get("type") or "win").lower()
            b["style"][ttype if ttype in b["style"] else "win"] = b["style"].get(ttype, 0) + 1
            if settlement["outcome"] == "win":
                b["wins"] += 1
            elif settlement["outcome"] == "place":
                b["places"] += 1
            else:
                b["losses"] += 1
        settled_races.append({
            "course": course, "time": time, "name": race.get("name"), "tips": stips,
        })

    settled = {
        "date": ds,
        "settled_at": datetime.utcnow().isoformat() + "Z",
        "summary": day_summary,
        "races": settled_races,
    }
    sp = ROOT / f"settled-{ds}.json"
    sp.write_text(json.dumps(settled, indent=2), encoding="utf-8")
    print(f"Wrote {sp} settled={day_summary['settled']} pnl={day_summary['pnl']:.2f}")

    # history: one entry per day
    lb["history"] = [h for h in lb.get("history") or [] if h.get("date") != ds]
    lb["history"].append(day_summary)
    lb["history"] = sorted(lb["history"], key=lambda x: x.get("date") or "")[-60:]
    lb["updated_at"] = datetime.utcnow().isoformat() + "Z"

    # clean internal keys for display file
    for b, stats in lb["bots"].items():
        stats.pop("_odds_sum", None)
        st = max(0.01, stats.get("stakes") or 0)
        stats["roi_pct"] = round(100.0 * (stats.get("pnl") or 0) / st, 1)
        tips_n = max(1, stats.get("tips") or 0)
        stats["win_pct"] = round(100.0 * (stats.get("wins") or 0) / tips_n, 1)

    lb_path.write_text(json.dumps(lb, indent=2), encoding="utf-8")
    print(f"Updated {lb_path}")


if __name__ == "__main__":
    main()
