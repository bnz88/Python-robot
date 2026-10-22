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

    const actions = document.createElement("span");
    actions.className = "log-card-actions";
    actions.innerHTML =
      '<button type="button" class="primary" data-act="start" title="Start scraping">Start</button>' +
      '<button type="button" data-act="stop" title="Stop scraping">Stop</button>';
    card.querySelector(".log-card-head").insertBefore(
      actions,
      card.querySelector(".log-card-status")
    );

    card.addEventListener("click", async (event) => {
      const btn = event.target.closest("button[data-act]");
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      try {
        await robotAction(String(r.id), btn.dataset.act);
      } catch (err) {
        setStatus(err.message, true);
      }
      await load();
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

  const startBtn = card.querySelector('button[data-act="start"]');
  const stopBtn = card.querySelector('button[data-act="stop"]');
  if (startBtn) startBtn.disabled = !r.online || !!r.running || !!r.auth_error;
  if (stopBtn) stopBtn.disabled = !r.online || !r.running;

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