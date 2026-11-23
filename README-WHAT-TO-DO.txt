HORSE RACING BOT — WHAT TO DO NOW
=================================

Your pipeline is solid. A few files were wrong / incomplete on GitHub.
Upload this pack, put the workflow in the right place, then re-run settle after races finish.

------------------------------------------------
1. UPLOAD THESE TO THE ROOT OF YOUR GITHUB REPO
------------------------------------------------
  index.html              (fixed: leaderboard tab actually loads data)
  settle_tips.py          (fixed: idempotent — re-runs no longer double-count)
  history_store.py        (fixed: reads meetings-based results)
  scrape_results.py
  scrape_racecards.py
  generate_tips.py
  requirements.txt
  leaderboard.json        (rebuilt from 22 + partial 23 Nov)
  settled-2026-11-22.json
  settled-2026-11-23.json
  results-2026-11-22.json
  results-2026-11-23.json (partial — only races finished by ~13:40 UTC)
  tips-2026-11-22.json / tips-2026-11-23.json (if not already there)
  history/                (runs.jsonl + stats_index.json)

------------------------------------------------
2. WORKFLOW FILE — CRITICAL PATH
------------------------------------------------
  GitHub Actions ONLY runs files from:
    .github/workflows/update-tips.yml

  Not from repo root. Copy update-tips.yml to that path.

  Schedule:
    07:30 UTC  →  scrape cards + generate tips (today + tomorrow)
    21:15 UTC  →  scrape results, settle, history, archive, commit

  Manual: Actions → Daily Racecards & Tips Update → Run workflow → mode "both" or "results"

------------------------------------------------
3. REPO SETTINGS
------------------------------------------------
  • Settings → Actions → General → allow workflows + read/write
  • Settings → Pages → Deploy from branch `main` / root (or /docs if you use that)
  • Commit as github-actions[bot] needs contents: write (already in yml)

------------------------------------------------
4. WHY LEADERBOARD WAS ALL ZEROS
------------------------------------------------
  settle_tips ran at ~12:00 UTC before most results existed → every tip "unknown".
  Re-running the old script would have double-counted.

  New settle_tips.py:
    - writes settled-YYYY-MM-DD.json for that day
    - rebuilds leaderboard from ALL settled-*.json (safe to re-run)

  After tonight's 21:15 job (or a manual "results" run), 23 Nov will fully settle
  and unknowns will drop for races that finished.

------------------------------------------------
5. DAILY FLOW (once workflow is live)
------------------------------------------------
  Morning  : racecards-*.json + tips-*.json for today & tomorrow
  Evening  : results-*.json → settled-*.json → leaderboard.json
             → history/runs.jsonl + stats_index.json
             → old day-files → history/archive/ (keeps last 3 days in root)

------------------------------------------------
6. OPTIONAL LOCAL CHECK
------------------------------------------------
  pip install -r requirements.txt
  python scrape_results.py --date yesterday
  python settle_tips.py --date yesterday
  python history_store.py --rebuild-day yesterday
  python history_store.py --archive --keep-days 3

------------------------------------------------
7. SITE
------------------------------------------------
  After push, hard-refresh the Pages URL (Ctrl+Shift+R).
  Leaderboard tab should show real tips / win% / ROI.
  Today / Tomorrow read tips-YYYY-MM-DD.json from the same folder as index.html.
