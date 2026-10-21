"use strict";

const container = $("#settings-container");

/* id -> {id, name, host, port} */
const robotMap = {};

function fieldHtml(field) {
  const key = esc(field.key);
  const type = field.type;
  const value = field.value == null ? "" : field.value;
  const help = field.help ? ` title="${esc(field.help)}"` : "";
  const ph = field.placeholder ? ` placeholder="${esc(field.placeholder)}"` : "";
  let control;
  if (type === "bool") {
    control = `<input type="checkbox" data-key="${key}" data-type="bool"${field.value ? " checked" : ""}${help}>`;
  } else if (type === "password") {
    control = `<input type="password" data-key="${key}" data-type="password" value="${esc(value)}" placeholder="Leave blank to keep current" autocomplete="new-password"${help}>`;
  } else if (type === "int" || type === "float") {
    const step = type === "float" ? "any" : "1";
    control = `<input type="number" step="${step}" data-key="${key}" data-type="${type}" value="${esc(value)}"${ph}${help}>`;
  } else if (type === "csv") {
    const joined = Array.isArray(value) ? value.join(", ") : value;
    control = `<input type="text" data-key="${key}" data-type="csv" value="${esc(joined)}"${ph}${help}>`;
  } else {
    control = `<input type="text" data-key="${key}" data-type="text" value="${esc(value)}"${ph}${help}>`;
  }
  return `<div class="field"><span class="fl">${esc(field.label)}</span>${control}</div>`;
}

function renderRobot(robot) {
  const section = document.createElement("section");
  section.className = "panel settings-card";
  section.id = "settings-" + robot.id;
  section.innerHTML = `
    <div class="settings-head">
      <div>
        <h2>${esc(robot.name)}</h2>
        <span class="acc-status">${esc(robot.host)}:${esc(robot.port)}</span>
      </div>
      <div class="settings-actions">
        <button data-act="reload" data-id="${robot.id}">Reload</button>
        <button class="primary" data-act="save" data-id="${robot.id}">Save changes</button>
      </div>
    </div>
    <div class="tabs" role="tablist"></div>
    <div class="tab-body"><p class="muted">Loading settings...</p></div>
    <p class="hint">Saved to this robot's config.json; changes take effect the next time the robot starts.</p>
  `;
  return section;
}

async function loadConfig(section, robot) {
  const tabbar = section.querySelector(".tabs");
  const body = section.querySelector(".tab-body");
  tabbar.innerHTML = "";
  body.innerHTML = '<p class="muted">Loading settings...</p>';
  let res;
  try {
    res = await get("/api/robots/" + robot.id + "/config");
  } catch (err) {
    body.innerHTML = `<p class="bad">${esc(err.message)}</p>`;
    return;
  }
  const tabs = res && res.tabs;
  if (!Array.isArray(tabs) || tabs.length === 0) {
    body.innerHTML = `<p class="bad">${esc((res && res.error) || "Failed to load settings")}</p>`;
    return;
  }
  tabbar.innerHTML = tabs
    .map(
      (t, i) =>
        `<button class="tab${i === 0 ? " active" : ""}" data-tab="${esc(t.id)}" role="tab">${esc(t.title)}</button>`
    )
    .join("");
  body.innerHTML = tabs
    .map((t, i) => {
      const fields =
        t.fields.map(fieldHtml).join("") || '<p class="muted">No settings.</p>';
      return `<div class="tab-panel${i === 0 ? " active" : ""}" data-panel="${esc(t.id)}"><div class="field-grid">${fields}</div></div>`;
    })
    .join("");
}

async function loadRobots() {
  container.innerHTML = '<p class="muted">Loading robots...</p>';
  let robots;
  try {
    robots = await get("/api/robots");
  } catch (err) {
    setStatus(err.message, true);
    return;
  }
  container.innerHTML = "";
  if (!Array.isArray(robots) || robots.length === 0) {
    container.innerHTML = '<p class="muted">No robots configured. Add a robot on the Dashboard first.</p>';
    return;
  }
  for (const r of robots) {
    robotMap[r.id] = { id: r.id, name: r.name, host: r.host, port: r.port };
    container.appendChild(renderRobot(r));
  }
  for (const r of Object.values(robotMap)) {
    await loadConfig($("#settings-" + r.id), r);
  }
}

function collectPayload(section) {
  const payload = {};
  for (const input of section.querySelectorAll("input[data-key]")) {
    const type = input.dataset.type;
    if (type === "bool") {
      payload[input.dataset.key] = input.checked;
    } else if (type === "int" || type === "float") {
      payload[input.dataset.key] = input.value === "" ? null : input.value;
    } else {
      payload[input.dataset.key] = input.value;
    }
  }
  return payload;
}

async function saveRobot(robot) {
  const section = $("#settings-" + robot.id);
  setStatus("Saving settings for " + robot.name + "...");
  try {
    const res = await post(
      "/api/robots/" + robot.id + "/config",
      collectPayload(section)
    );
    if (res.error) {
      setStatus(res.error, true);
      return;
    }
    setStatus("Settings saved for " + robot.name + ".");
    await loadConfig(section, robot);
  } catch (err) {
    setStatus(err.message, true);
  }
}

function switchTab(btn) {
  const section = btn.closest(".settings-card");
  if (!section) return;
  const id = btn.dataset.tab;
  for (const b of section.querySelectorAll(".tabs .tab")) {
    b.classList.toggle("active", b === btn);
  }
  for (const p of section.querySelectorAll(".tab-panel")) {
    p.classList.toggle("active", p.dataset.panel === id);
  }
}

async function onAction(e) {
  const tab = e.target.closest(".tab");
  if (tab) {
    switchTab(tab);
    return;
  }
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const robot = robotMap[btn.dataset.id];
  if (!robot) return;
  if (btn.dataset.act === "save") {
    await saveRobot(robot);
  } else if (btn.dataset.act === "reload") {
    setStatus("Reloading settings for " + robot.name + "...");
    await loadConfig($("#settings-" + robot.id), robot);
  }
}

function init() {
  container.addEventListener("click", onAction);
  loadRobots();
}

init();
