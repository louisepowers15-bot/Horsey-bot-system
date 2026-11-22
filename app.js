/**
 * Horse Racing Bot Chat - Main application
 */

let todayData = null;
let tomorrowData = null;
let currentData = null;
let currentTab = "today";

const SAMPLE_DATA = {
  date: "2026-11-21",
  meetings: ["Ascot", "Haydock", "Punchestown"],
  races: []
};

function getDateOffset(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function fetchTipsForDate(dateStr) {
  // Try root folder first, then data/ subfolder as backup
  for (const path of [`./tips-${dateStr}.json`, `./data/tips-${dateStr}.json`]) {
    try {
      const res = await fetch(`${path}?t=${Date.now()}`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) { /* try next path */ }
  }
  return null;
}

async function loadTips() {
  const todayStr = getDateOffset(0);
  const tomorrowStr = getDateOffset(1);

  todayData = await fetchTipsForDate(todayStr);
  tomorrowData = await fetchTipsForDate(tomorrowStr);

  currentData = todayData || SAMPLE_DATA;
  updateHeaderDate(currentData.date || todayStr);
}

function updateHeaderDate(dateStr) {
  const dateObj = new Date(dateStr + "T12:00:00");
  const formatted = dateObj.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
  // Update any subtitle/date element on the page
  document.querySelectorAll("p, .subtitle, #date-display").forEach(el => {
    if (el.textContent.includes("UK & Ireland")) {
      el.textContent = `UK & Ireland · ${formatted}`;
    }
  });
}

function confClass(c) {
  if (c >= 60) return "conf-high";
  if (c >= 45) return "conf-mid";
  return "conf-low";
}

function renderStars(n) {
  return "★".repeat(n) + "☆".repeat(Math.max(0, 4 - n));
}

function renderRacecards(dataSet) {
  if (!dataSet || !dataSet.races || dataSet.races.length === 0) {
    return `<p style="color:#94a3b8;text-align:center;padding:2rem">No racecards available yet for this date.</p>`;
  }

  const meetings = {};
  dataSet.races.forEach(r => {
    if (!meetings[r.course]) meetings[r.course] = [];
    meetings[r.course].push(r);
  });

  let html = "";
  Object.keys(meetings).sort().forEach(course => {
    html += `<div class="meeting"><div class="meeting-title">${course}</div>`;
    meetings[course].forEach(race => {
      html += `
        <div class="race">
          <div class="race-header">
            ${race.time} · ${race.name}
          </div>
          ${race.tips.map(t => {
            const bot = BOTS[t.bot] || { colour: "#64748b", name: t.bot };
            return `
              <div class="tip">
                <span class="bot-badge" style="background:${bot.colour}">${bot.name}</span>
                <span class="horse-name">${t.horse}${t.type === "ew" ? '<span class="ew-flag">E/W</span>' : ""}</span>
                <span class="stars">${renderStars(t.stars || 1)}</span>
                <span class="odds">${Number(t.odds).toFixed(2)}</span>
                <span class="confidence ${confClass(t.conf)}">${t.conf}%</span>
              </div>
            `;
          }).join("")}
        </div>
      `;
    });
    html += `</div>`;
  });
  return html;
}

function renderLeaderboard() {
  const lb = loadLeaderboard();
  const rows = Object.entries(lb.bots).map(([id, b]) => {
    const bot = BOTS[id] || { name: id, colour: "#64748b" };
    const roi = b.stakes > 0 ? ((b.returns - b.stakes) / b.stakes * 100) : 0;
    const winRate = b.tips > 0 ? (b.wins / b.tips * 100) : 0;
    return `
      <tr>
        <td><span class="bot-badge" style="background:${bot.colour}">${bot.name}</span></td>
        <td>${b.tips}</td>
        <td>${winRate.toFixed(1)}%</td>
        <td class="${roi >= 0 ? "roi-pos" : "roi-neg"}">${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%</td>
        <td>${b.avgOdds.toFixed(2)}</td>
        <td>${b.style.short}/${b.style.ew}/${b.style.longshot}</td>
      </tr>
    `;
  }).join("");

  return `
    <div style="margin-bottom:1rem;display:flex;gap:0.75rem;flex-wrap:wrap">
      <button class="tab" onclick="exportLeaderboard()">Export JSON</button>
      <label class="tab" style="cursor:pointer">
        Import JSON
        <input type="file" accept=".json" style="display:none" onchange="handleImport(event)">
      </label>
    </div>
    <table class="lb-table">
      <thead>
        <tr>
          <th>Bot</th>
          <th>Tips</th>
          <th>Win %</th>
          <th>ROI</th>
          <th>Avg Odds</th>
          <th>Style (S/EW/L)</th>
        </tr>
      </thead>
      <tbody>
        ${rows || "<tr><td colspan='6' style='text-align:center;color:#94a3b8'>No results recorded yet</td></tr>"}
      </tbody>
    </table>
    <p style="margin-top:1rem;color:#94a3b8;font-size:0.85rem">
      Style = Short-priced / Each-way / Longshot. Level stakes assumed. Results must be entered manually for now.
    </p>
  `;
}

function renderContent() {
  const el = document.getElementById("content");
  if (currentTab === "today") {
    updateHeaderDate(getDateOffset(0));
    el.innerHTML = renderRacecards(todayData || SAMPLE_DATA);
  } else if (currentTab === "tomorrow") {
    updateHeaderDate(getDateOffset(1));
    el.innerHTML = renderRacecards(tomorrowData);
  } else if (currentTab === "leaderboard") {
    el.innerHTML = renderLeaderboard();
  } else if (currentTab === "big") {
    el.innerHTML = `<p style="color:#94a3b8;text-align:center;padding:2rem">Big race focus view coming next.</p>`;
  } else if (currentTab === "doubles") {
    el.innerHTML = `<p style="color:#94a3b8;text-align:center;padding:2rem">Doubles & Accas view coming next.</p>`;
  }
}
