/**
 * Horse Racing Bot Chat
 */

let todayData = null;
let tomorrowData = null;
let currentTab = "today";

const BOTS = window.BOTS || {
  BloodlineBetty: { name: "BloodlineBetty", colour: "#ec4899" },
  DevilAdvocate:  { name: "DevilAdvocate",  colour: "#a855f7" },
  FormFox:        { name: "FormFox",        colour: "#3b82f6" },
  HotTrainer:     { name: "HotTrainer",     colour: "#ef4444" },
  PaceProphet:    { name: "PaceProphet",    colour: "#f97316" },
  ValueHunter:    { name: "ValueHunter",    colour: "#22c55e" }
};

function getDateOffset(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function fetchTipsForDate(dateStr) {
  for (const path of [`./tips-${dateStr}.json`, `./data/tips-${dateStr}.json`]) {
    try {
      const res = await fetch(`${path}?t=${Date.now()}`);
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.races) && data.races.length > 0) return data;
      }
    } catch (e) {}
  }
  return null;
}

async function loadTips() {
  todayData = await fetchTipsForDate(getDateOffset(0));
  tomorrowData = await fetchTipsForDate(getDateOffset(1));
}

function updateHeaderDate(dateStr) {
  const el = document.getElementById("header-meta");
  if (!el) return;
  try {
    const formatted = new Date(dateStr + "T12:00:00").toLocaleDateString("en-GB", {
      weekday: "long", day: "numeric", month: "long", year: "numeric"
    });
    el.textContent = `UK & Ireland · ${formatted}`;
  } catch (e) {
    el.textContent = `UK & Ireland · ${dateStr}`;
  }
}

function confClass(c) {
  if (c >= 60) return "conf-high";
  if (c >= 45) return "conf-mid";
  return "conf-low";
}

function renderStars(n) {
  n = Number(n) || 0;
  if (n < 2) return "";
  return "★".repeat(Math.min(n, 6));
}

function groupByMeeting(races) {
  const map = {};
  (races || []).forEach(r => {
    const c = r.course || "Unknown";
    if (!map[c]) map[c] = [];
    map[c].push(r);
  });
  return map;
}

function renderRacecards(dataSet, openAll = false) {
  if (!dataSet || !dataSet.races || dataSet.races.length === 0) {
    return `<p style="color:#94a3b8;text-align:center;padding:2.5rem">No tips available for this date yet.</p>`;
  }

  const meetings = groupByMeeting(dataSet.races);
  let html = "";

  Object.keys(meetings).sort().forEach(course => {
    html += `
      <div class="meeting${openAll ? " open" : ""}">
        <div class="meeting-header" onclick="this.parentElement.classList.toggle('open')">
          <span>${course}</span>
          <span class="chevron">▶</span>
        </div>
        <div class="meeting-body">`;

    meetings[course].forEach(race => {
      html += `
        <div class="race">
          <div class="race-header">
            <span class="race-time">${race.time || ""}</span>
            <span class="race-name">${race.name || ""}</span>
          </div>
          <div class="col-headers">
            <div>Bot</div>
            <div>Horse</div>
            <div style="text-align:center">Stars</div>
            <div style="text-align:right">Odds</div>
            <div style="text-align:center">Conf</div>
          </div>`;

      (race.tips || []).forEach(t => {
        const bot = BOTS[t.bot] || { name: t.bot, colour: "#64748b" };
        html += `
          <div class="tip" onclick="this.classList.toggle('open')">
            <span class="bot-badge" style="background:${bot.colour}">${bot.name}</span>
            <span class="horse-name">${t.horse}${t.type === "ew" ? '<span class="ew-flag">E/W</span>' : ""}</span>
            <span class="stars">${renderStars(t.stars)}</span>
            <span class="odds">${Number(t.odds).toFixed(2)}</span>
            <span class="confidence ${confClass(t.conf)}">${t.conf}%</span>
            <div class="reason-panel"><strong>${bot.name}:</strong> ${t.reason || "No reasoning available."}</div>
          </div>`;
      });
      html += `</div>`;
    });
    html += `</div></div>`;
  });
  return html;
}

/* ---------- Hot Pick ---------- */
function getHotPick(dataSet) {
  if (!dataSet || !dataSet.races) return null;
  const scores = {};
  dataSet.races.forEach(race => {
    (race.tips || []).forEach(t => {
      const key = `${race.course}|${race.time}|${t.horse}`;
      if (!scores[key]) {
        scores[key] = { horse: t.horse, course: race.course, time: race.time, race: race.name, odds: t.odds, total: 0, count: 0, bots: [] };
      }
      scores[key].total += Number(t.conf) || 0;
      scores[key].count += 1;
      scores[key].bots.push(t.bot);
      if (t.odds) scores[key].odds = t.odds;
    });
  });
  const list = Object.values(scores).map(s => ({
    ...s,
    avg: s.total / s.count,
    combined: s.total
  }));
  list.sort((a, b) => b.combined - a.combined || b.avg - a.avg);
  return list[0] || null;
}

function renderHotPick() {
  const hot = getHotPick(todayData);
  if (!hot) {
    return `<p style="color:#94a3b8;text-align:center;padding:2rem">No hot pick available yet.</p>`;
  }
  return `
    <div class="section-title">Today’s Hot Pick</div>
    <div class="card hot-pick">
      <h3>${hot.horse}</h3>
      <p><strong>${hot.course}</strong> · ${hot.time}<br>${hot.race}</p>
      <p style="margin-top:0.5rem">Odds: <strong>${Number(hot.odds).toFixed(2)}</strong> · 
         Combined confidence: <strong>${Math.round(hot.combined)}</strong> 
         (${hot.count} bots · avg ${Math.round(hot.avg)}%)</p>
      <p style="margin-top:0.35rem;color:#94a3b8;font-size:0.85rem">Bots: ${hot.bots.join(", ")}</p>
    </div>
    <p style="color:#94a3b8;font-size:0.85rem">Highest combined confidence across all bots today.</p>
  `;
}

/* ---------- Doubles & Accas ---------- */
function topSelections(dataSet, typeFilter, limit) {
  if (!dataSet || !dataSet.races) return [];
  const picks = [];
  dataSet.races.forEach(race => {
    const byHorse = {};
    (race.tips || []).forEach(t => {
      if (typeFilter && t.type !== typeFilter) return;
      if (!byHorse[t.horse]) byHorse[t.horse] = { horse: t.horse, course: race.course, time: race.time, odds: t.odds, conf: 0, count: 0, type: t.type };
      byHorse[t.horse].conf += Number(t.conf) || 0;
      byHorse[t.horse].count += 1;
      byHorse[t.horse].odds = t.odds;
    });
    Object.values(byHorse).forEach(p => {
      p.avg = p.conf / p.count;
      picks.push(p);
    });
  });
  picks.sort((a, b) => b.count - a.count || b.avg - a.avg);
  // unique horses
  const seen = new Set();
  const unique = [];
  for (const p of picks) {
    if (seen.has(p.horse)) continue;
    seen.add(p.horse);
    unique.push(p);
    if (unique.length >= limit) break;
  }
  return unique;
}

function renderDoubles() {
  const winPicks = topSelections(todayData, "win", 8);
  const ewPicks = topSelections(todayData, "ew", 8);
  const allPicks = topSelections(todayData, null, 10);

  function combo(list, n, label) {
    if (list.length < n) return `<div class="card"><h3>${label}</h3><p>Not enough selections yet.</p></div>`;
    const chosen = list.slice(0, n);
    const names = chosen.map(p => `${p.horse} (${p.course} ${p.time})`).join(" + ");
    const odds = chosen.reduce((a, p) => a * (Number(p.odds) || 2), 1);
    return `
      <div class="card">
        <h3>${label}</h3>
        <p>${names}</p>
        <p style="margin-top:0.35rem;color:#94a3b8;font-size:0.85rem">Approx combined odds: ${odds.toFixed(1)}</p>
      </div>`;
  }

  return `
    <div class="section-title">Doubles & Accas (from today’s strongest consensus)</div>
    ${combo(winPicks, 2, "Winners Double")}
    ${combo(ewPicks, 2, "Each-Way Double")}
    ${combo(winPicks, 3, "Winners Treble")}
    ${combo(ewPicks, 3, "Each-Way Treble")}
    ${combo(allPicks, 6, "6-Fold (mixed)")}
    <p style="color:#94a3b8;font-size:0.85rem;margin-top:1rem">Built from highest bot agreement. Always check current odds and terms.</p>
  `;
}

/* ---------- Big Festivals ---------- */
function renderBigFestivals() {
  const festivals = [
    { name: "Cheltenham Festival", when: "March · 4 days", note: "Champion Hurdle, Champion Chase, Stayers’, Gold Cup, Ryanair + supporting Grade 1s" },
    { name: "Aintree Grand National Meeting", when: "April · 3 days", note: "Grand National, Mersey Novices’, Mildmay, Aintree Hurdle, Maghull, Topham" },
    { name: "Punchestown Festival", when: "Late April / early May · 5 days", note: "Irish Champion races, Gold Cup, Champion Chase, Champion Stayers" },
    { name: "Royal Ascot", when: "June · 5 days", note: "Queen Anne, Prince of Wales’s, Gold Cup, Diamond Jubilee, Commonwealth Cup, Coronation" },
    { name: "Glorious Goodwood", when: "Late July / early August · 5 days", note: "Sussex Stakes, Goodwood Cup, Nassau, Lennox, Richmond" },
    { name: "York Ebor Festival", when: "August · 4 days", note: "International, Yorkshire Oaks, Nunthorpe, Ebor Handicap, Lonsdale Cup" },
    { name: "Irish Champions Weekend", when: "September · Leopardstown & Curragh", note: "Irish Champion Stakes, Matron, National Stakes, Moyglare, Flying Five" },
    { name: "Newmarket Autumn / Cambridgeshire", when: "September–October", note: "Cambridgeshire, Cesarewitch, Dewhurst, Fillies’ Mile, Middle Park, Cheveley Park" },
    { name: "British Champions Day", when: "October · Ascot", note: "Champion Stakes, QEII, Champions Sprint, Fillies & Mares, Long Distance Cup" },
    { name: "King George & Christmas", when: "December · Kempton / Ireland", note: "King George VI Chase, Christmas Hurdle, Savills Chase, Dublin Racing Festival (Feb)" }
  ];
  return `
    <div class="section-title">Major Festivals & Meetings</div>
    <p style="color:#94a3b8;font-size:0.9rem;margin-bottom:1rem">The big meetings the bots will focus on when the cards are available.</p>
    ${festivals.map(f => `
      <div class="card">
        <h3>${f.name}</h3>
        <p style="color:#94a3b8;font-size:0.85rem;margin-bottom:0.3rem">${f.when}</p>
        <p>${f.note}</p>
      </div>
    `).join("")}
  `;
}

function renderLeaderboard() {
  return `
    <div class="section-title">Bot Leaderboard</div>
    <p style="color:#94a3b8;text-align:center;padding:1.5rem">
      Results tracking will appear here once we start recording daily outcomes.<br>
      It will show tips, win %, ROI, average odds and emerging style for each bot.
    </p>
  `;
}

function renderContent() {
  const el = document.getElementById("content");
  if (!el) return;

  if (currentTab === "today") {
    updateHeaderDate((todayData && todayData.date) || getDateOffset(0));
    el.innerHTML = renderRacecards(todayData, false);
  } else if (currentTab === "tomorrow") {
    updateHeaderDate((tomorrowData && tomorrowData.date) || getDateOffset(1));
    el.innerHTML = renderRacecards(tomorrowData, false);
  } else if (currentTab === "hot") {
    updateHeaderDate((todayData && todayData.date) || getDateOffset(0));
    el.innerHTML = renderHotPick();
  } else if (currentTab === "big") {
    el.innerHTML = renderBigFestivals();
  } else if (currentTab === "doubles") {
    el.innerHTML = renderDoubles();
  } else if (currentTab === "leaderboard") {
    el.innerHTML = renderLeaderboard();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const tabs = document.getElementById("main-tabs");
  if (tabs) {
    tabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab");
      if (!btn) return;
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      renderContent();
    });
  }
});

(async function boot() {
  try { await loadTips(); } catch (e) { console.error(e); }
  renderContent();
})();
