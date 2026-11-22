/**
 * Horse Racing Bot Chat - Main application
 */

let todayData = null;
let tomorrowData = null;
let currentData = null;
let currentTab = "today";

const SAMPLE_DATA = {
  date: "2026-11-21",
  meetings: [],
  races: []
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
        if (data && data.races && data.races.length > 0) return data;
      }
    } catch (e) { /* try next */ }
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
  const el = document.getElementById("header-meta");
  if (!el) return;
  try {
    const dateObj = new Date(dateStr + "T12:00:00");
    const formatted = dateObj.toLocaleDateString("en-GB", {
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
  n = n || 0;
  if (n < 2) return "";
  return "★".repeat(Math.min(n, 6));
}

function renderRacecards(dataSet) {
  if (!dataSet || !dataSet.races || dataSet.races.length === 0) {
    return `<p style="color:#94a3b8;text-align:center;padding:2rem">No tips available yet for this date.<br>The daily update may still be running.</p>`;
  }

  const meetings = {};
  dataSet.races.forEach(r => {
    if (!meetings[r.course]) meetings[r.course] = [];
    meetings[r.course].push(r);
  });

  let html = "";
  Object.keys(meetings).sort().forEach(course => {
    html += `<div class="meeting open">
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
            <div>Bot</div><div>Horse</div><div style="text-align:center">Stars</div>
            <div style="text-align:right">Odds</div><div style="text-align:center">Conf</div>
          </div>`;

      (race.tips || []).forEach(t => {
        const bot = (window.BOTS && window.BOTS[t.bot]) || { name: t.bot, colour: "#64748b" };
        html += `
          <div class="tip" onclick="this.classList.toggle('open')">
            <span class="bot-badge" style="background:${bot.colour}">${bot.name}</span>
            <span class="horse-name">${t.horse}${t.type === "ew" ? '<span class="ew-flag">E/W</span>' : ""}</span>
            <span class="stars">${renderStars(t.stars)}</span>
            <span class="odds">${Number(t.odds).toFixed(2)}</span>
            <span class="confidence ${confClass(t.conf)}">${t.conf}%</span>
            <div class="reason-panel"><strong>${bot.name}:</strong> ${t.reason || "No reasoning provided."}</div>
          </div>`;
      });
      html += `</div>`;
    });
    html += `</div></div>`;
  });
  return html;
}

function renderLeaderboard() {
  return `<p style="color:#94a3b8;text-align:center;padding:2rem">Leaderboard coming soon.<br>Results will be tracked here.</p>`;
}

function renderContent() {
  const el = document.getElementById("content");
  if (!el) return;

  if (currentTab === "today") {
    updateHeaderDate((todayData && todayData.date) || getDateOffset(0));
    el.innerHTML = renderRacecards(todayData);
  } else if (currentTab === "tomorrow") {
    updateHeaderDate((tomorrowData && tomorrowData.date) || getDateOffset(1));
    el.innerHTML = renderRacecards(tomorrowData);
  } else if (currentTab === "leaderboard") {
    el.innerHTML = renderLeaderboard();
  } else if (currentTab === "big") {
    el.innerHTML = `<p style="color:#94a3b8;text-align:center;padding:2rem">Big Festivals view coming next.</p>`;
  } else if (currentTab === "doubles") {
    el.innerHTML = `<p style="color:#94a3b8;text-align:center;padding:2rem">Doubles & Accas view coming next.</p>`;
  }
}

// Tab clicks
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

// Boot
(async function boot() {
  try {
    await loadTips();
  } catch (e) {
    console.error(e);
    todayData = SAMPLE_DATA;
  }
  renderContent();
})();
