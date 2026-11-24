#!/usr/bin/env python3
"""
Long-term racing history for bot pattern use + repo tidy.

After results are scraped:
  1. Merge results + racecards into history/runs.jsonl
     (horse, date, course, distance, surface, code, going, position, trainer, jockey, odds)
  2. Rebuild history/stats_index.json for fast lookups
  3. Move day files older than KEEP_DAYS into history/archive/
     so the repo root only keeps recent racecards/tips/results

Usage:
  python history_store.py --rebuild-day 2026-11-23
  python history_store.py --rebuild-day yesterday
  python history_store.py --archive
  python history_store.py --all-pending   # rebuild from any results-* not yet fully archived
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "history"
ARCHIVE = HIST / "archive"
RUNS = HIST / "runs.jsonl"
INDEX = HIST / "stats_index.json"
KEEP_DAYS = 3  # keep this many days of day-files in repo root


def parse_date(arg: str) -> date:
    if arg.lower() == "today":
        return date.today()
    if arg.lower() == "yesterday":
        return date.today() - timedelta(days=1)
    return datetime.strptime(arg, "%Y-%m-%d").date()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def distance_bucket(dist: str) -> str:
    if not dist:
        return "unknown"
    d = dist.lower().replace("½", ".5").replace("¼", ".25")
    miles = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*m", d)
    if m:
        miles += float(m.group(1))
    f = re.search(r"(\d+(?:\.\d+)?)\s*f", d)
    if f:
        miles += float(f.group(1)) / 8.0
    y = re.search(r"(\d+)\s*y", d)
    if y and miles == 0:
        miles = float(y.group(1)) / 1760.0
    if miles <= 0:
        return "unknown"
    if miles < 1.1:
        return "sprint"
    if miles < 1.6:
        return "mile"
    if miles < 2.2:
        return "middle"
    if miles < 2.8:
        return "staying"
    return "extreme"


def going_bucket(going: str) -> str:
    g = (going or "").lower()
    if not g:
        return "unknown"
    if any(x in g for x in ("heavy", "soft", "yielding")):
        return "soft"
    if any(x in g for x in ("firm", "hard")):
        return "firm"
    if any(x in g for x in ("standard", "poly", "tapeta", "aw", "dirt")):
        return "aw"
    if "good" in g:
        return "good"
    return "unknown"


def detect_surface(course: str, going: str, explicit: str = "") -> str:
    if explicit in ("AW", "turf"):
        return explicit
    g = (going or "").lower()
    c = (course or "").lower()
    aw = {"newcastle", "wolverhampton", "lingfield", "chelmsford", "southwell", "kempton", "dundalk"}
    if any(x in g for x in ("standard", "polytrack", "tapeta", "fibresand", "dirt")):
        return "AW"
    if c in aw and "good" not in g and "soft" not in g:
        return "AW"
    if g:
        return "turf"
    return "unknown"


def detect_code(name: str, explicit: str = "") -> str:
    if explicit in ("flat", "hurdle", "chase", "nh_flat"):
        return explicit
    n = (name or "").lower()
    if re.search(r"\bchase\b|\bsteeplechase\b", n):
        return "chase"
    if re.search(r"\bhurdle\b", n):
        return "hurdle"
    if re.search(r"\bbumper\b|\bn\.?h\.?\s*flat\b", n):
        return "nh_flat"
    return explicit or "unknown"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_runs() -> list[dict]:
    if not RUNS.exists():
        return []
    out = []
    for line in RUNS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def append_runs(records: list[dict]) -> int:
    HIST.mkdir(parents=True, exist_ok=True)
    existing = {
        (r.get("date"), norm(r.get("course") or ""), r.get("time") or "", norm(r.get("horse") or ""))
        for r in load_runs()
    }
    added = 0
    with RUNS.open("a", encoding="utf-8") as f:
        for r in records:
            key = (r.get("date"), norm(r.get("course") or ""), r.get("time") or "", norm(r.get("horse") or ""))
            if key in existing:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            existing.add(key)
            added += 1
    return added


def rebuild_day(day: str) -> int:
    """Merge results + racecards for one day into history/runs.jsonl.

    Accepts both scraper shapes:
      - meetings[].races[].runners[]  (current scrape_results.py)
      - top-level races[] with positions[] (legacy)
    """
    results = load_json(ROOT / f"results-{day}.json")
    if not results:
        results = load_json(ARCHIVE / f"results-{day}.json")
    if not results:
        print(f"No results for {day}")
        return 0

    cards = load_json(ROOT / f"racecards-{day}.json") or load_json(ARCHIVE / f"racecards-{day}.json") or {}
    card_races = {}
    for m in cards.get("meetings") or []:
        course = m.get("course") or ""
        m_going = m.get("going") or ""
        for race in m.get("races") or []:
            t = (race.get("time") or "").strip()
            key = (norm(course), t)
            card_races[key] = {
                "course": course,
                "time": t,
                "name": race.get("name") or "",
                "distance": race.get("distance") or "",
                "going": race.get("going") or m_going,
                "surface": race.get("surface") or "",
                "code": race.get("code") or "",
                "runners": {norm(x.get("name") or ""): x for x in race.get("runners") or []},
            }

    # Normalize results into a flat list of races with runners
    flat_races = []
    if results.get("meetings"):
        for m in results["meetings"]:
            m_course = m.get("course") or ""
            for race in m.get("races") or []:
                flat_races.append({
                    **race,
                    "course": race.get("course") or m_course,
                })
    elif results.get("races"):
        flat_races = list(results["races"])

    if not flat_races:
        print(f"No races in results for {day}")
        return 0

    records = []
    for race in flat_races:
        course = race.get("course") or ""
        time_s = (race.get("time") or "").strip()
        card = card_races.get((norm(course), time_s), {})
        distance = race.get("distance") or card.get("distance") or ""
        going = race.get("going") or card.get("going") or ""
        surface = detect_surface(course, going, race.get("surface") or card.get("surface") or "")
        code = detect_code(race.get("name") or card.get("name") or "", race.get("code") or card.get("code") or "")
        race_name = race.get("name") or card.get("name") or ""

        # runners[] with position/sp (current) OR positions[] (legacy)
        pos_map = {}
        for ru in race.get("runners") or []:
            hn = norm(ru.get("name") or "")
            if hn:
                pos_map[hn] = {
                    "horse": ru.get("name"),
                    "pos": ru.get("position"),
                    "sp": ru.get("sp") or ru.get("odds"),
                    "trainer": ru.get("trainer") or "",
                    "jockey": ru.get("jockey") or "",
                    "status": ru.get("status") or "",
                }
        for p in race.get("positions") or []:
            hn = norm(p.get("horse") or p.get("name") or "")
            if hn and hn not in pos_map:
                pos_map[hn] = {
                    "horse": p.get("horse") or p.get("name"),
                    "pos": p.get("pos") or p.get("position"),
                    "sp": p.get("sp") or p.get("odds"),
                    "trainer": p.get("trainer") or "",
                    "jockey": p.get("jockey") or "",
                }

        names = set(pos_map.keys()) | set((card.get("runners") or {}).keys())
        field_size = race.get("field_size") or len(names) or len(pos_map)

        for hn in names:
            pre = (card.get("runners") or {}).get(hn, {})
            post = pos_map.get(hn, {})
            horse = post.get("horse") or pre.get("name") or hn
            pos = post.get("pos")
            try:
                pos = int(pos) if pos is not None else None
            except Exception:
                pos = None
            # Non-runners / DNF
            status = (post.get("status") or "").upper()
            if status in ("NR", "NON-RUNNER", "WD") and pos is None:
                continue
            records.append({
                "date": day,
                "course": course,
                "time": time_s,
                "race": race_name,
                "distance": distance,
                "distance_bucket": distance_bucket(distance),
                "going": going,
                "going_bucket": going_bucket(going),
                "surface": surface,
                "code": code,
                "field_size": field_size,
                "horse": horse,
                "position": pos,
                "won": pos == 1,
                "placed": isinstance(pos, int) and 1 <= pos <= 3,
                "trainer": pre.get("trainer") or post.get("trainer") or "",
                "jockey": pre.get("jockey") or post.get("jockey") or "",
                "odds": pre.get("odds") or post.get("sp") or post.get("odds"),
                "form": pre.get("form") or "",
            })

    added = append_runs(records)
    print(f"History {day}: +{added} runs (candidates {len(records)})")
    rebuild_index()
    return added


def _rate(wins: int, n: int, prior: float = 0.12, prior_n: float = 8.0) -> float:
    if n <= 0:
        return prior
    return (wins + prior * prior_n) / (n + prior_n)


def rebuild_index() -> dict:
    runs = load_runs()
    tables = {
        "trainer_course": defaultdict(lambda: [0, 0]),
        "trainer_code": defaultdict(lambda: [0, 0]),
        "trainer_surface": defaultdict(lambda: [0, 0]),
        "jockey_trainer": defaultdict(lambda: [0, 0]),
        "horse_course": defaultdict(lambda: [0, 0]),
        "horse_surface": defaultdict(lambda: [0, 0]),
        "horse_code": defaultdict(lambda: [0, 0]),
        "horse_going": defaultdict(lambda: [0, 0]),
        "horse_distance": defaultdict(lambda: [0, 0]),
        "horse_place_surface": defaultdict(lambda: [0, 0]),
        "horse_place_code": defaultdict(lambda: [0, 0]),
    }

    for r in runs:
        if r.get("position") is None:
            continue
        won = 1 if r.get("won") else 0
        placed = 1 if r.get("placed") else 0
        t, j, h = norm(r.get("trainer") or ""), norm(r.get("jockey") or ""), norm(r.get("horse") or "")
        c = norm(r.get("course") or "")
        surface = r.get("surface") or "unknown"
        code = r.get("code") or "unknown"
        gb = r.get("going_bucket") or "unknown"
        db = r.get("distance_bucket") or "unknown"

        def add(table, key, w=won, p=None):
            tables[table][key][0] += w if p is None else p
            tables[table][key][1] += 1

        if t and c:
            add("trainer_course", (t, c))
        if t and code != "unknown":
            add("trainer_code", (t, code))
        if t and surface != "unknown":
            add("trainer_surface", (t, surface))
        if t and j:
            add("jockey_trainer", (j, t))
        if h and c:
            add("horse_course", (h, c))
        if h and surface != "unknown":
            add("horse_surface", (h, surface))
            add("horse_place_surface", (h, surface), w=0, p=placed)
        if h and code != "unknown":
            add("horse_code", (h, code))
            add("horse_place_code", (h, code), w=0, p=placed)
        if h and gb != "unknown":
            add("horse_going", (h, gb))
        if h and db != "unknown":
            add("horse_distance", (h, db))

    def pack(d, place=False):
        out = {}
        for k, (a, n) in d.items():
            key = "|".join(k) if isinstance(k, tuple) else str(k)
            if place:
                out[key] = {"places": a, "n": n, "rate": round(_rate(a, n, prior=0.28, prior_n=6), 4)}
            else:
                out[key] = {"wins": a, "n": n, "rate": round(_rate(a, n), 4)}
        return out

    index = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runs": len(runs),
        "trainer_course": pack(tables["trainer_course"]),
        "trainer_code": pack(tables["trainer_code"]),
        "trainer_surface": pack(tables["trainer_surface"]),
        "jockey_trainer": pack(tables["jockey_trainer"]),
        "horse_course": pack(tables["horse_course"]),
        "horse_surface": pack(tables["horse_surface"]),
        "horse_code": pack(tables["horse_code"]),
        "horse_going": pack(tables["horse_going"]),
        "horse_distance": pack(tables["horse_distance"]),
        "horse_place_surface": pack(tables["horse_place_surface"], place=True),
        "horse_place_code": pack(tables["horse_place_code"], place=True),
    }
    HIST.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Index rebuilt: {index['runs']} runs → {INDEX}")
    return index


def load_index() -> dict:
    if INDEX.exists():
        return json.loads(INDEX.read_text(encoding="utf-8"))
    return rebuild_index() if RUNS.exists() else {"runs": 0}


def lookup(table: dict, *parts: str, default: float = 0.12) -> tuple[float, int]:
    key = "|".join(norm(p) if p not in {
        "sprint", "mile", "middle", "staying", "extreme", "soft", "firm", "good", "aw", "unknown",
        "flat", "hurdle", "chase", "nh_flat", "AW", "turf",
    } else p for p in parts)
    # Also try fully normed
    rec = table.get(key) or table.get("|".join(norm(p) for p in parts))
    if not rec:
        return default, 0
    return float(rec.get("rate", default)), int(rec.get("n") or 0)


def horse_history_bits(index: dict, horse: str, course: str, surface: str, code: str, going: str, distance: str) -> list[str]:
    """Plain-English facts from history for reasons (only if sample size useful)."""
    bits = []
    if not index or int(index.get("runs") or 0) == 0:
        return bits
    hs = index.get("horse_surface") or {}
    hc = index.get("horse_code") or {}
    hcourse = index.get("horse_course") or {}
    rate, n = lookup(hs, horse, surface)
    if n >= 2 and surface in ("AW", "turf"):
        bits.append(f"In our saved results, {horse} has {n} run(s) on {surface} (win rate about {rate:.0%} after caution for small samples)")
    rate, n = lookup(hc, horse, code)
    if n >= 2 and code in ("flat", "hurdle", "chase", "nh_flat"):
        bits.append(f"On {code} races in our history: {n} run(s)")
    rate, n = lookup(hcourse, horse, course)
    if n >= 2 and course:
        bits.append(f"At {course} in our history: {n} run(s)")
    return bits


def archive_old_day_files(keep_days: int = KEEP_DAYS) -> int:
    """
    Move racecards/tips/results/settled older than keep_days into history/archive/.
    Leaves recent files in repo root for the website + debugging.
    """
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    cutoff = date.today() - timedelta(days=keep_days)
    moved = 0
    patterns = ["racecards-*.json", "tips-*.json", "results-*.json", "settled-*.json"]
    for pat in patterns:
        for path in ROOT.glob(pat):
            # parse date from filename
            m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
            if not m:
                continue
            try:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if d >= cutoff:
                continue
            dest = ARCHIVE / path.name
            shutil.move(str(path), str(dest))
            moved += 1
            print(f"Archived {path.name} → history/archive/")
    return moved


def rebuild_all_pending() -> None:
    """Find all results-* in root or archive and ensure they're in runs.jsonl."""
    days = set()
    for p in list(ROOT.glob("results-*.json")) + list(ARCHIVE.glob("results-*.json")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        if m:
            days.add(m.group(1))
    for day in sorted(days):
        rebuild_day(day)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-day", help="YYYY-MM-DD | today | yesterday")
    parser.add_argument("--archive", action="store_true", help="Move old day-files into history/archive")
    parser.add_argument("--all-pending", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    args = parser.parse_args()

    if args.rebuild_day:
        d = parse_date(args.rebuild_day)
        rebuild_day(d.isoformat())
    if args.all_pending:
        rebuild_all_pending()
    if args.stats:
        rebuild_index()
    if args.archive:
        n = archive_old_day_files(args.keep_days)
        print(f"Archived {n} files (kept last {args.keep_days} days in root)")
    if not any([args.rebuild_day, args.all_pending, args.stats, args.archive]):
        runs = load_runs()
        print(f"History runs: {len(runs)} at {RUNS}")
        if INDEX.exists():
            idx = json.loads(INDEX.read_text(encoding="utf-8"))
            print(f"Index runs: {idx.get('runs')} updated {idx.get('updated_at')}")


if __name__ == "__main__":
    main()
