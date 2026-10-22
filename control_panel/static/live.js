"use strict";

const grid = $("#live-grid");
const cards = {};

function renderRobot(r) {
  let card = cards[String(r.id)];
  if (!card) {
    card = document.createElement("div");
    card.className = "live-card";
    card.innerHTML = `
      <div class="log-card-head">
        <span class="log-card-title"></span>
        <span class="log-card-status"></span>
      </div>
      <div class="log-card-acc"></div>
      <div class="live-frame">
        <img class="live-card-img" alt="live view" style="visibility:hidden">
        <span class="live-placeholder">no footage</span>
      </div>`;
    grid.appendChild(card);
    cards[String(r.id)] = card;

    const img = card.querySelector(".live-card-img");
    const placeholder = card.querySelector(".live-placeholder");
    img.addEventListener("load", () => {
      img.style.visibility = "visible";
      placeholder.style.display = "none";
    });
    img.addEventListener("error", () => {
      img.style.visibility = "hidden";
      placeholder.style.display = "";
    });
  }

  card.querySelector(".log-card-title").textContent = `${r.name} (${r.host}:${r.port})`;

  let statusText = "offline";
  let cls = "bad";
  if (r.online) {
    cls = r.auth_error ? "warn" : "ok";
    statusText = r.auth_error ? "auth failed" : r.running ? "RUNNING" : "stopped";
  }
  const st = card.querySelector(".log-card-status");
  st.className = "log-card-status " + cls;
  st.textContent = statusText;

  card.querySelector(".log-card-acc").textContent =
    `now: ${r.current_account || "-"}  |  next: ${r.next_account || "-"}`;

  const img = card.querySelector(".live-card-img");
  img.setAttribute("src", `/api/robots/${r.id}/live?t=${Date.now()}`);
}

async function load() {
  const robots = await get("/api/robots");
  const seen = new Set();
  robots.forEach((r) => {
    seen.add(String(r.id));
    renderRobot(r);
  });
  for (const id of Object.keys(cards)) {
    if (!seen.has(id)) {
      cards[id].remove();
      delete cards[id];
    }
  }
}

function init() {
  load();
  const refreshMs = Number(grid.dataset.refreshMs) || 1000;
  setInterval(load, refreshMs);
}

init();
