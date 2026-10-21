"use strict";

const grid = $("#log-grid");
const cards = {};

function renderRobot(r, text) {
  let card = cards[String(r.id)];
  if (!card) {
    card = document.createElement("div");
    card.className = "log-card";
    card.innerHTML = `
      <div class="log-card-head">
        <span class="log-card-title"></span>
        <span class="log-card-status"></span>
      </div>
      <div class="log-card-acc"></div>
      <pre class="log-card-body"></pre>`;
    grid.appendChild(card);
    cards[String(r.id)] = card;
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

  const acc = card.querySelector(".log-card-acc");
  acc.textContent = `now: ${r.current_account || "-"}  |  next: ${r.next_account || "-"}`;

  const body = card.querySelector(".log-card-body");
  if (body.textContent !== text) {
    body.textContent = text;
    body.scrollTop = body.scrollHeight;
  }
}

async function load() {
  const robots = await get("/api/robots");
  const lines = parseInt($("#log-lines").value || "150", 10);
  const seen = new Set();
  await Promise.all(
    robots.map(async (r) => {
      seen.add(String(r.id));
      const data = await get(`/api/robots/${r.id}/log?lines=${lines}`);
      renderRobot(r, data && data.text != null ? data.text : "");
    })
  );
  for (const id of Object.keys(cards)) {
    if (!seen.has(id)) {
      cards[id].remove();
      delete cards[id];
    }
  }
}

function init() {
  load();
  setInterval(load, 2000);
}

init();