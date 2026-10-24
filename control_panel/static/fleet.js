"use strict";

const state = {
  robots: [],
  proxies: [],
};

async function loadRobots() {
  state.robots = await get("/api/robots");
  renderRobots();
}

function renderRobots() {
  const tbody = $("#robots-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!state.robots.length) {
    tbody.innerHTML =
      '<tr><td class="cell-empty" colspan="7">No robots registered yet - add one below.</td></tr>';
    return;
  }
  for (const r of state.robots) {
    const tr = document.createElement("tr");

    let statusText = "offline";
    let statusCls = "bad";
    if (r.online) {
      statusCls = r.auth_error ? "warn" : "ok";
      statusText = r.auth_error ? "auth failed" : "online";
    }
    const proxy =
      r.default_proxy_ip && r.default_proxy_port
        ? `${r.default_proxy_ip}:${r.default_proxy_port}`
        : "";

    tr.innerHTML = `
      <td>${esc(r.name)}</td>
      <td>${esc(r.host)}:${esc(String(r.port))}</td>
      <td class="${statusCls}">${esc(statusText)}</td>
      <td>${r.running ? "running" : "stopped"}</td>
      <td>${r.pid == null ? "" : esc(String(r.pid))}</td>
      <td>${esc(proxy)}</td>
      <td>
        <button data-act="start" data-id="${r.id}"${r.running ? " disabled" : ""}>Start</button>
        <button data-act="stop" data-id="${r.id}"${r.running ? "" : " disabled"}>Stop</button>
        <button data-act="edit" data-id="${r.id}">Edit</button>
        <button data-act="delete" data-id="${r.id}">Delete</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function startRobot(id) {
  const proxies = (state.proxies || []).map((p) => ({ ip: p.ip, port: p.port }));
  const body = proxies.length ? { proxy: "auto", proxies } : {};
  try {
    const res = await post(`/api/robots/${id}/start`, body);
    if (res.error) setStatus(res.error, true);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadRobots();
}

async function stopRobot(id) {
  try {
    const res = await post(`/api/robots/${id}/stop`);
    if (res.error) setStatus(res.error, true);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadRobots();
}

async function loadProxyOptions() {
  state.proxies = await get("/api/proxies");
  const proxyOptions = (state.proxies || [])
    .map(
      (p) =>
        `<option value="${p.id}">${esc(String(p.ip) + ":" + String(p.port))}${p.note ? " (" + esc(p.note) + ")" : ""}</option>`
    )
    .join("");
  document.querySelectorAll(".proxy-select").forEach((sel) => {
    const keep = sel.value;
    sel.innerHTML = '<option value="">proxy: none</option>' + proxyOptions;
    sel.value =
      keep && Array.from(sel.options).some((o) => o.value === keep) ? keep : "";
  });
}

function openEdit(id) {
  const r = state.robots.find((x) => String(x.id) === String(id));
  if (!r) return;
  const form = $("#edit-form");
  form.id.value = r.id;
  form.name.value = r.name;
  form.host.value = r.host;
  form.port.value = r.port;
  form.token.value = r.token || "";
  const proxySel = form.querySelector(".proxy-select");
  const match = (state.proxies || []).find(
    (p) =>
      p.ip === r.default_proxy_ip &&
      String(p.port) === String(r.default_proxy_port || "")
  );
  proxySel.value = match ? String(match.id) : "";
  $("#edit-dialog").showModal();
}

async function submitEdit(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const id = fd.get("id");
  try {
    await post(`/api/robots/${id}/edit`, Object.fromEntries(fd.entries()));
  } catch (err) {
    setStatus(err.message, true);
  }
  $("#edit-dialog").close();
  await loadRobots();
}

async function submitAdd(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await post("/api/robots", Object.fromEntries(fd.entries()));
  } catch (err) {
    setStatus(err.message, true);
  }
  e.target.reset();
  await loadProxyOptions();
  await loadRobots();
}

function onRobotAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn || btn.disabled) return;
  const { act, id } = btn.dataset;
  if (act === "start") startRobot(id);
  else if (act === "stop") stopRobot(id);
  else if (act === "edit") openEdit(id);
  else if (act === "delete") {
    if (confirm("Delete this robot?")) {
      post(`/api/robots/${id}/delete`).then(loadRobots);
    }
  }
}

function init() {
  $("#edit-cancel").addEventListener("click", () => $("#edit-dialog").close());
  $("#edit-form").addEventListener("submit", submitEdit);
  $("#add-robot-form").addEventListener("submit", submitAdd);
  $("#robots-table tbody").addEventListener("click", onRobotAction);
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".min-toggle");
    if (!t) return;
    const panel = t.closest(".panel");
    if (!panel) return;
    const collapsed = panel.classList.toggle("collapsed");
    t.textContent = collapsed ? "+" : "−";
  });
  loadProxyOptions();
  loadRobots();
  setInterval(loadRobots, 2500);
}

init();
