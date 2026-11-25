#!/usr/bin/env python3
"""
Match tips to results and update leaderboard.json

Settlement rules (level £1 stake):
  WIN tip:  win  -> return = odds; else 0
  E/W tip:  stake split 0.5 win + 0.5 place
            place terms by field size: >=12 -> 1/4 odds 3 places;
            >=8 -> 1/5 odds 3 places; >=5 -> 1/4 odds 2 places; else win-only

Idempotent: each run writes settled-YYYY-MM-DD.json for that day, then
rebuilds leaderboard.json from ALL settled-*.json files so re-runs do not double-count.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Leaderboard counts only settled days on/after this date (reset point)
LEADERBOARD_FROM = date(2026, 11, 25)

BOTS = [
    "FormFox", "HotTrainer", "BloodlineBetty", "DevilAdvocate",
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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def result_index(results: dict):
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
                # treat 0 / negative as non-finisher (NR / PU etc.) — still known outcome
                try:
                    pos_i = int(pos) if pos is not None else None
                except (TypeError, ValueError):
                    pos_i = None
                if pos_i is not None and pos_i <= 0:
                    # finished status unknown / DNF — mark as high position so lose
                    pos_i = 99
                by_ct_h[(course.lower(), time, h)] = pos_i
                by_c_h[(course.lower(), h)] = pos_i
                by_h[h] = pos_i
    return by_ct_h, by_c_h, by_h, field_by_ct


def settle_tip(tip, pos, field_size):
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
            "position": pos if pos < 99 else None,
        }

    terms = place_terms(field_size or 0)
    if not terms:
        won = pos == 1
        ret = odds if won else 0.0
        return {
            "outcome": "win" if won else "lose",
            "stake": stake,
            "return": ret,
            "pnl": ret - stake,
            "position": pos if pos < 99 else None,
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
        "position": pos if pos < 99 else None,
        "place_terms": f"{frac} odds, {places} places",
    }


def empty_bot():
    return {
        "tips": 0, "wins": 0, "places": 0, "losses": 0, "unknown": 0,
        "stakes": 0.0, "returns": 0.0, "pnl": 0.0,
        "avg_odds": 0.0, "_odds_sum": 0.0,
        "style": {"win": 0, "ew": 0},
        # confidence calibration buckets
        "conf": {
            "low": {"n": 0, "wins": 0},      # conf < 55
            "mid": {"n": 0, "wins": 0},      # 55–69
            "high": {"n": 0, "wins": 0},     # 70+
        },
    }


def settle_one_day(d: date) -> dict | None:
    ds = d.isoformat()
    tips = load_json(ROOT / f"tips-{ds}.json")
    results = load_json(ROOT / f"results-{ds}.json")
    if not tips:
        print(f"No tips file for {ds}")
        return None
    if not results:
        print(f"No results file for {ds} — run scrape_results.py first")
        return None

    by_ct_h, by_c_h, by_h, field_by_ct = result_index(results)
    settled_races = []
    day_summary = {"date": ds, "tips": 0, "settled": 0, "unknown": 0, "pnl": 0.0}

    for race in tips.get("races") or []:
        course = race.get("course") or ""
        time = race.get("time") or ""
        field = field_by_ct.get((course.lower(), time)) or 8
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
            if settlement["outcome"] == "unknown":
                day_summary["unknown"] += 1
            else:
                day_summary["settled"] += 1
                day_summary["pnl"] += settlement["pnl"]
        settled_races.append({
            "course": course, "time": time, "name": race.get("name"), "tips": stips,
        })

    settled = {
        "date": ds,
        "settled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": day_summary,
        "races": settled_races,
    }
    sp = ROOT / f"settled-{ds}.json"
    sp.write_text(json.dumps(settled, indent=2), encoding="utf-8")
    print(f"Wrote {sp} settled={day_summary['settled']} unknown={day_summary['unknown']} pnl={day_summary['pnl']:.2f}")
    return settled


def _finalise_bot_stats(stats: dict) -> dict:
    tips_n = stats.get("tips") or 0
    if tips_n:
        stats["avg_odds"] = round(stats.get("_odds_sum", 0) / tips_n, 2)
        stats["win_pct"] = round(100.0 * (stats.get("wins") or 0) / tips_n, 1)
    else:
        stats["avg_odds"] = 0.0
        stats["win_pct"] = 0.0
    stats.pop("_odds_sum", None)
    st = max(0.01, stats.get("stakes") or 0)
    stats["roi_pct"] = round(100.0 * (stats.get("pnl") or 0) / st, 1) if (stats.get("stakes") or 0) else 0.0
    stats["pnl"] = round(stats.get("pnl") or 0, 2)
    stats["stakes"] = round(stats.get("stakes") or 0, 2)
    stats["returns"] = round(stats.get("returns") or 0, 2)
    conf = stats.get("conf") or {}
    for k in ("low", "mid", "high"):
        bucket = conf.get(k) or {"n": 0, "wins": 0}
        n = bucket.get("n") or 0
        bucket["win_pct"] = round(100.0 * (bucket.get("wins") or 0) / n, 1) if n else 0.0
        conf[k] = bucket
    stats["conf"] = conf
    return stats


def _conf_bucket(conf) -> str:
    try:
        c = int(conf)
    except (TypeError, ValueError):
        c = 50
    if c >= 70:
        return "high"
    if c >= 55:
        return "mid"
    return "low"


def _apply_tip(bucket: dict, tip: dict) -> None:
    bot = tip.get("bot")
    if not bot:
        return
    if bot not in bucket:
        bucket[bot] = empty_bot()
    b = bucket[bot]
    outcome = tip.get("outcome") or "unknown"
    if outcome == "unknown":
        b["unknown"] += 1
        return
    b["tips"] += 1
    b["stakes"] += float(tip.get("stake") or 0)
    b["returns"] += float(tip.get("return") or 0)
    b["pnl"] += float(tip.get("pnl") or 0)
    b["_odds_sum"] += float(tip.get("odds") or 0)
    ttype = (tip.get("type") or "win").lower()
    if ttype not in ("win", "ew"):
        ttype = "win"
    b["style"][ttype] = b["style"].get(ttype, 0) + 1
    won = outcome == "win"
    if won:
        b["wins"] += 1
    elif outcome == "place":
        b["places"] += 1
    else:
        b["losses"] += 1
    # confidence calibration
    if "conf" not in b:
        b["conf"] = {"low": {"n": 0, "wins": 0}, "mid": {"n": 0, "wins": 0}, "high": {"n": 0, "wins": 0}}
    ck = _conf_bucket(tip.get("conf"))
    b["conf"][ck]["n"] += 1
    if won:
        b["conf"][ck]["wins"] += 1


def rebuild_leaderboard_from_settled() -> dict:
    """Rebuild leaderboard from every settled-*.json (idempotent).

    Also builds period slices: week (last 7 calendar days), month (last 30),
    year (last 365), and all-time. Tracks hot-pick (consensus) performance.
    """
    today = date.today()
    periods = {
        "all": {"bots": {b: empty_bot() for b in BOTS}},
        "week": {"bots": {b: empty_bot() for b in BOTS}},
        "month": {"bots": {b: empty_bot() for b in BOTS}},
        "year": {"bots": {b: empty_bot() for b in BOTS}},
    }
    history = []
    hot = {"n": 0, "wins": 0, "places": 0, "stakes": 0.0, "returns": 0.0, "pnl": 0.0, "days": []}
    files = sorted(ROOT.glob("settled-*.json"))
    for path in files:
        data = load_json(path)
        if not data:
            continue
        summary = data.get("summary") or {}
        ds = data.get("date") or summary.get("date")
        day = None
        if ds:
            try:
                day = datetime.strptime(ds, "%Y-%m-%d").date()
            except ValueError:
                day = None
        # Reset: ignore history before LEADERBOARD_FROM
        if day is not None and day < LEADERBOARD_FROM:
            continue
        if day is None:
            # try parse from filename settled-YYYY-MM-DD.json
            import re as _re
            m = _re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
            if m:
                try:
                    day = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    if day < LEADERBOARD_FROM:
                        continue
                except ValueError:
                    continue
            else:
                continue
            history.append({
                "date": ds,
                "tips": summary.get("tips") or 0,
                "settled": summary.get("settled") or 0,
                "unknown": summary.get("unknown") or 0,
                "pnl": round(float(summary.get("pnl") or 0), 2),
            })
        day_hot = {"n": 0, "wins": 0, "pnl": 0.0}
        for race in data.get("races") or []:
            tips = race.get("tips") or []
            for tip in tips:
                _apply_tip(periods["all"]["bots"], tip)
                if day is None:
                    continue
                age = (today - day).days
                if age <= 7:
                    _apply_tip(periods["week"]["bots"], tip)
                if age <= 30:
                    _apply_tip(periods["month"]["bots"], tip)
                if age <= 365:
                    _apply_tip(periods["year"]["bots"], tip)

            # Hot pick = horse with most bot agreement in the race (stars >= 3)
            if not tips:
                continue
            best_stars = max(int(t.get("stars") or 0) for t in tips)
            if best_stars < 3:
                continue
            # one representative tip for that horse (prefer highest conf)
            consensus = [t for t in tips if int(t.get("stars") or 0) == best_stars]
            consensus.sort(key=lambda t: int(t.get("conf") or 0), reverse=True)
            hp = consensus[0]
            outcome = hp.get("outcome") or "unknown"
            if outcome == "unknown":
                continue
            stake = 1.0
            ret = float(hp.get("return") or 0)
            # if this tip was EW, return is already for £1 total; use as-is
            # for consensus we treat as win-only level £1 using odds if win else 0
            if (hp.get("type") or "win").lower() == "ew":
                # approximate win-only settlement for consensus card
                odds = float(hp.get("odds") or 0)
                ret = odds if outcome == "win" else 0.0
            pnl = ret - stake
            hot["n"] += 1
            hot["stakes"] += stake
            hot["returns"] += ret
            hot["pnl"] += pnl
            day_hot["n"] += 1
            day_hot["pnl"] += pnl
            if outcome == "win":
                hot["wins"] += 1
                day_hot["wins"] += 1
            elif outcome == "place":
                hot["places"] += 1
        if day_hot["n"]:
            hot["days"].append({
                "date": ds,
                "n": day_hot["n"],
                "wins": day_hot["wins"],
                "pnl": round(day_hot["pnl"], 2),
            })

    for period in periods.values():
        for bot, stats in period["bots"].items():
            _finalise_bot_stats(stats)

    # Best tipster per period (by ROI, min 5 settled tips)
    for key, period in periods.items():
        ranked = [
            (bid, s) for bid, s in period["bots"].items()
            if (s.get("tips") or 0) >= 5
        ]
        ranked.sort(key=lambda x: (x[1].get("roi_pct") or -999), reverse=True)
        period["best_roi"] = ranked[0][0] if ranked else None
        ranked_w = sorted(
            [(bid, s) for bid, s in period["bots"].items() if (s.get("tips") or 0) >= 5],
            key=lambda x: (x[1].get("win_pct") or -1),
            reverse=True,
        )
        period["best_win"] = ranked_w[0][0] if ranked_w else None

    # Finalise hot pick stats
    hot["pnl"] = round(hot["pnl"], 2)
    hot["stakes"] = round(hot["stakes"], 2)
    hot["returns"] = round(hot["returns"], 2)
    hot["win_pct"] = round(100.0 * hot["wins"] / hot["n"], 1) if hot["n"] else 0.0
    hot["roi_pct"] = round(100.0 * hot["pnl"] / hot["stakes"], 1) if hot["stakes"] else 0.0

    lb = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reset_from": LEADERBOARD_FROM.isoformat(),
        "bots": periods["all"]["bots"],  # back-compat for older UI
        "periods": periods,
        "best_roi": periods["all"]["best_roi"],
        "best_win": periods["all"]["best_win"],
        "hot_pick": hot,
        "history": sorted(history, key=lambda x: x.get("date") or "")[-90:],
    }

    # Track freshest settled day
    last_dates = sorted(
        (h.get("date") for h in history if h.get("date")),
        reverse=True,
    )
    last_settled = last_dates[0] if last_dates else None
    lb["last_settled"] = last_settled
    lb["updated_at"] = datetime.now(timezone.utc).isoformat()

    path = ROOT / "leaderboard.json"
    path.write_text(json.dumps(lb, indent=2), encoding="utf-8")

    # Lightweight status for the site header
    status = {
        "last_settled": last_settled,
        "updated_at": lb["updated_at"],
        "best_roi": lb.get("best_roi"),
        "best_win": lb.get("best_win"),
        "settled_days": len(files),
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    print(f"Rebuilt {path} from {len(files)} settled day file(s); last_settled={last_settled}; best ROI={lb['best_roi']}; hot n={hot['n']}")
    return lb


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="yesterday")
    p.add_argument("--rebuild-only", action="store_true", help="Only rebuild leaderboard from existing settled-*.json")
    args = p.parse_args()

    if not args.rebuild_only:
        d = parse_date(args.date)
        settle_one_day(d)
    rebuild_leaderboard_from_settled()


if __name__ == "__main__":
    main()
