/**
 * Leaderboard & history persistence
 * Uses localStorage + optional JSON export/import
 */

const STORAGE_KEY = "hrbc_leaderboard_v1";
const HISTORY_KEY = "hrbc_tip_history_v1";

function loadLeaderboard() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createEmptyLeaderboard();
    return JSON.parse(raw);
  } catch (e) {
    console.warn("Could not load leaderboard", e);
    return createEmptyLeaderboard();
  }
}

function saveLeaderboard(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function createEmptyLeaderboard() {
  const bots = ["BloodlineBetty", "DevilAdvocate", "FormFox", "HotTrainer", "PaceProphet", "ValueHunter"];
  const empty = {
    bots: {},
    lastUpdated: null,
    version: 1
  };
  bots.forEach(id => {
    empty.bots[id] = {
      tips: 0,
      wins: 0,
      places: 0,
      stakes: 0,
      returns: 0,
      avgOdds: 0,
      style: { short: 0, ew: 0, longshot: 0 },
      daily: {},
      weekly: {},
      monthly: {},
      yearly: {}
    };
  });
  return empty;
}

function recordResult(botId, tip) {
  // tip = { horse, odds, type: "win"|"ew", result: "win"|"place"|"lose", returned: number }
  const lb = loadLeaderboard();
  const b = lb.bots[botId];
  if (!b) return;

  b.tips += 1;
  b.stakes += 1; // level stakes for now
  b.returns += tip.returned || 0;

  if (tip.result === "win") b.wins += 1;
  if (tip.result === "place" || tip.result === "win") b.places += 1;

  // style
  if (tip.odds <= 3.0) b.style.short += 1;
  else if (tip.type === "ew") b.style.ew += 1;
  else b.style.longshot += 1;

  // rolling average odds
  b.avgOdds = ((b.avgOdds * (b.tips - 1)) + tip.odds) / b.tips;

  lb.lastUpdated = new Date().toISOString();
  saveLeaderboard(lb);
  return lb;
}

function exportLeaderboard() {
  const data = loadLeaderboard();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `leaderboard-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function importLeaderboard(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        saveLeaderboard(data);
        resolve(data);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

if (typeof window !== "undefined") {
  window.loadLeaderboard = loadLeaderboard;
  window.saveLeaderboard = saveLeaderboard;
  window.recordResult = recordResult;
  window.exportLeaderboard = exportLeaderboard;
  window.importLeaderboard = importLeaderboard;
}
