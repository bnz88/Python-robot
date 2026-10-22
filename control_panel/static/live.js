"use strict";

const grid = $("#live-grid");
const cards = {};
const robotsById = new Map();

const modal = $("#live-modal");
const modalImg = $("#live-modal-img");
const modalTitle = $("#live-modal-title");
const modalClose = $("#live-modal-close");
let modalRobotId = null;

function liveUrl(id) {
  return `/api/robots/${id}/live?t=${Date.now()}`;
}

function openZoom(robot) {
  modalRobotId = String(robot.id);
  modalTitle.textContent = `${robot.name} (${robot.host}:${robot.port})`;
  modalImg.src = liveUrl(robot.id);
  modal.showModal();
}

function closeZoom() {
  modalRobotId = null;
  modalImg.removeAttribute("src");
  if (modal.open) {
    modal.close();
  }
}

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

    const zoom = document.createElement("button");
    zoom.type = "button";
    zoom.className = "live-zoom";
    zoom.title = "Enlarge live view";
    zoom.setAttribute("aria-label", "Enlarge live view");
    zoom.innerHTML =
      '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">' +
      '<path fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" d="M4 9V4h5M20 15v5h-5M15 4h5v5M9 20H4v-5"/></svg>';
    zoom.addEventListener("click", () => {
      const info = robotsById.get(String(r.id));
      if (info) openZoom(info);
    });
    card.querySelector(".log-card-head").appendChild(zoom);
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
  img.setAttribute("src", liveUrl(r.id));
}

async function load() {
  const robots = await get("/api/robots");
  const seen = new Set();
  robots.forEach((r) => {
    robotsById.set(String(r.id), r);
    seen.add(String(r.id));
    renderRobot(r);
  });
  for (const id of Object.keys(cards)) {
    if (!seen.has(id)) {
      cards[id].remove();
      delete cards[id];
      robotsById.delete(id);
      if (modalRobotId === id) closeZoom();
    }
  }
  if (modalRobotId !== null) {
    const info = robotsById.get(modalRobotId);
    if (info) {
      modalImg.src = liveUrl(info.id);
    } else {
      closeZoom();
    }
  }
}

function init() {
  load();
  const refreshMs = Number(grid.dataset.refreshMs) || 1000;
  setInterval(load, refreshMs);

  modalClose.addEventListener("click", closeZoom);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeZoom();
    }
  });
  modal.addEventListener("close", () => {
    modalRobotId = null;
    modalImg.removeAttribute("src");
  });
}

init();
