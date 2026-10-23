"use strict";

const IS_ADMIN = window.PANEL_ROLE === "admin";
const LIVE_REFRESH_MS =
  Number((document.querySelector("main") || {}).dataset?.refreshMs) || 1000;

const state = {
  robots: [],
  selectedId: null,
  autoLog: true,
  proxies: [],
  omittedEditing: null,
};

async function loadRobots() {
  state.robots = await get("/api/robots");
  renderRobots();
  const stillSelected = state.robots.some(
    (r) => String(r.id) === String(state.selectedId)
  );
  if (state.selectedId && !stillSelected) {
    state.selectedId = null;
    $("#robot-controls").hidden = true;
  }
  if (state.selectedId) await refreshSelected();
  refreshLive();
}

function renderRobots() {
  const tbody = $("#robots-table tbody");
  tbody.innerHTML = "";
  for (const r of state.robots) {
    const tr = document.createElement("tr");
    if (String(r.id) === String(state.selectedId)) tr.classList.add("selected");

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
        <button data-act="select" data-id="${r.id}">Select</button>
        <button data-act="start" data-id="${r.id}">Start</button>
        <button data-act="stop" data-id="${r.id}">Stop</button>
        ${
          IS_ADMIN
            ? `<button data-act="edit" data-id="${r.id}">Edit</button>
        <button data-act="delete" data-id="${r.id}">Delete</button>`
            : ""
        }
      </td>`;
    tbody.appendChild(tr);
  }

  const sel = state.robots.find((x) => String(x.id) === String(state.selectedId));
  if (sel) {
    $("#selected-name").textContent = sel.name;
    $("#selected-status").textContent = `now: ${sel.current_account || "-"}  |  next: ${sel.next_account || "-"}`;
  }
}

async function refreshSelected() {
  if (!state.selectedId) return;
  await Promise.all([loadAccounts(), loadLogIfAuto()]);
}

async function loadAccounts() {
  const id = state.selectedId;
  if (!id) return;
  const accounts = await get(`/api/robots/${id}/accounts`);
  renderAccounts(accounts);
}

function renderAccounts(accounts) {
  if (state.omittedEditing) return;
  const tbody = $("#accounts-table tbody");
  tbody.innerHTML = "";
  if (!Array.isArray(accounts)) return;
  const sel = state.robots.find((x) => String(x.id) === String(state.selectedId));
  let current = null;
  let next = null;
  if (sel && sel.running) {
    current = sel.current_account;
    next = sel.next_account;
  }
  for (const a of accounts) {
    const last = a.last_scrape
      ? new Date(a.last_scrape * 1000).toLocaleString()
      : "-";
    const tr = document.createElement("tr");
    if (current && a.label === current) {
      tr.classList.add("row-current");
    } else if (next && a.label === next) {
      tr.classList.add("row-next");
    }
    tr.innerHTML = `
      <td>${esc(a.label)}</td>
      <td>${esc(a.bank || "")}</td>
      <td>${esc(a.unique_id ?? "")}</td>
      <td>${esc(a.bank_shortname ?? "")}</td>
      <td>${a.enabled ? "yes" : "no"}</td>
      <td>${a.output_exists ? "yes" : "no"}</td>
      <td>${esc(last)}</td>
      <td><input class="omitted-input" data-label="${esc(a.label)}" value="${esc(a.omitted_rows == null ? "" : a.omitted_rows)}" placeholder="auto"></td>
      <td>
        <button data-act="next" data-label="${esc(a.label)}">Jump Next</button>
        <button data-act="view" data-label="${esc(a.label)}" data-bank="${esc(a.bank || "")}">View</button>
        ${
          a.enabled
            ? `<button class="btn-ban" data-act="ban" data-label="${esc(a.label)}">Ban</button>`
            : `<button class="btn-unban" data-act="unban" data-label="${esc(a.label)}">Unban</button>`
        }
        <button data-act="remove" data-label="${esc(a.label)}">Remove</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function loadLogIfAuto() {
  if (!state.autoLog) return;
  const id = state.selectedId;
  if (!id) return;
  const lines = parseInt($("#log-lines").value || "200", 10);
  const data = await get(`/api/robots/${id}/log?lines=${lines}`);
  const pane = $("#log-pane");
  const text = data && data.text != null ? data.text : "";
  if (pane.textContent !== text) {
    pane.textContent = text;
    pane.scrollTop = pane.scrollHeight;
  }
}

async function selectRobot(id) {
  state.selectedId = id;
  const r = state.robots.find((x) => String(x.id) === String(id));
  if (!r) return;
  $("#selected-name").textContent = r.name;
  const proxySel = $("#proxy-select");
  const proxyMatch = (state.proxies || []).find(
    (p) => p.ip === r.default_proxy_ip && String(p.port) === String(r.default_proxy_port || "")
  );
  proxySel.value = proxyMatch ? String(proxyMatch.id) : "";
  $("#robot-controls").hidden = false;
  $("#accounts-title").textContent = "Accounts - " + r.name;
  $("#log-title").textContent = "Log - " + r.name;
  renderRobots();
  await refreshSelected();
}

async function startRobot() {
  const id = state.selectedId;
  if (!id) return;
  const proxyId = $("#proxy-select").value;
  const proxy = (state.proxies || []).find((p) => String(p.id) === String(proxyId));
  const body = {
    proxy_ip: proxy ? proxy.ip : "",
    proxy_port: proxy ? String(proxy.port) : "",
    account: $("#account-select").value,
  };
  try {
    await post(`/api/robots/${id}/start`, body);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadRobots();
}

async function stopRobot() {
  const id = state.selectedId;
  if (!id) return;
  try {
    await post(`/api/robots/${id}/stop`);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadRobots();
}

async function toggleAccount(label, action) {
  const id = state.selectedId;
  if (!id) return;
  try {
    await post(`/api/robots/${id}/accounts/${encodeURIComponent(label)}/${action}`);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadAccounts();
}

async function removeAccount(label) {
  const id = state.selectedId;
  if (!id) return;
  if (!confirm(`Remove account "${label}" from this robot?`)) return;
  try {
    await post("/api/accounts/remove", { robot_id: id, label });
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadAccounts();
}

async function viewStatement(label, bank) {
  const id = state.selectedId;
  const data = await get(
    `/api/robots/${id}/statement/${encodeURIComponent(label)}?bank=${encodeURIComponent(bank)}`
  );
  $("#statement-body").textContent =
    data && data.text != null ? data.text : "(no output yet)";
  $("#statement-dialog").showModal();
}

async function copyStatement() {
  const body = $("#statement-body");
  // Select everything in the statement first, so the text is highlighted and
  // the legacy copy command has a selection to work with.
  const range = document.createRange();
  range.selectNodeContents(body);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const text = selection.toString() || body.textContent || "";
  if (!text.trim()) {
    setStatus("Statement is empty - nothing to copy.", true);
    return;
  }
  let copied = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch (err) {
    copied = false;
  }
  if (!copied) {
    // Plain-http panels are not a secure context, so fall back to copying the
    // current selection.
    try {
      copied = document.execCommand("copy");
    } catch (err) {
      copied = false;
    }
  }
  const button = $("#statement-copy");
  if (copied) {
    button.classList.add("copied");
    window.setTimeout(() => button.classList.remove("copied"), 1200);
  }
  setStatus(
    copied
      ? "Statement selected and copied to the clipboard."
      : "Copy failed - the statement is selected, press Ctrl+C.",
    !copied
  );
}

function selectedRobot() {
  return (
    state.robots.find((x) => String(x.id) === String(state.selectedId)) || null
  );
}

function applyLiveControls(container, robot) {
  const start = container.querySelector('button[data-act="start"]');
  const stop = container.querySelector('button[data-act="stop"]');
  const blocked = !robot.online || !!robot.auth_error;
  if (start) start.disabled = blocked || !!robot.running;
  if (stop) stop.disabled = blocked || !robot.running;
  const status = container.querySelector(".log-card-status");
  if (status) {
    const text = blocked
      ? robot.auth_error
        ? "auth failed"
        : "offline"
      : robot.running
        ? "RUNNING"
        : "stopped";
    const cls = blocked ? "bad" : robot.running ? "ok" : "bad";
    status.className = "log-card-status " + cls;
    status.textContent = text;
  }
}

function refreshLive() {
  const panel = $("#live-panel");
  const robot = selectedRobot();
  const modal = $("#live-modal");
  if (!robot) {
    panel.hidden = true;
    if (modal.open) modal.close();
    return;
  }
  panel.hidden = false;
  $("#live-title").textContent = "Live feed - " + robot.name;
  $("#live-img").src = `/api/robots/${robot.id}/live?t=${Date.now()}`;
  applyLiveControls(panel, robot);
  if (modal.open) {
    $("#live-modal-title").textContent = `${robot.name} (${robot.host}:${robot.port})`;
    $("#live-modal-img").src = `/api/robots/${robot.id}/live?t=${Date.now()}`;
    applyLiveControls(modal, robot);
  }
}

function wireLiveFeed() {
  const img = $("#live-img");
  const placeholder = document.querySelector("#live-panel .live-placeholder");
  img.addEventListener("load", () => {
    img.style.visibility = "visible";
    placeholder.style.display = "none";
  });
  img.addEventListener("error", () => {
    img.style.visibility = "hidden";
    placeholder.style.display = "";
  });

  $("#live-start").addEventListener("click", startRobot);
  $("#live-stop").addEventListener("click", stopRobot);
  $("#live-zoom").addEventListener("click", () => {
    refreshLive();
    $("#live-modal").showModal();
  });
  $("#live-modal-close").addEventListener("click", () => $("#live-modal").close());
  $("#live-modal").addEventListener("click", (event) => {
    if (event.target.closest('button[data-act="start"]')) {
      startRobot();
    } else if (event.target.closest('button[data-act="stop"]')) {
      stopRobot();
    } else if (event.target === $("#live-modal")) {
      $("#live-modal").close();
    }
  });
  window.setInterval(refreshLive, LIVE_REFRESH_MS);
}

async function loadProxyOptions() {
  state.proxies = await get("/api/proxies");
  const optionHtml =
    '<option value="">proxy: none</option>' +
    (state.proxies || [])
      .map((p) => `<option value="${p.id}">${esc(String(p.ip) + ":" + String(p.port))}${p.note ? " (" + esc(p.note) + ")" : ""}</option>`)
      .join("");
  document.querySelectorAll(".proxy-select").forEach((sel) => {
    const keep = sel.value;
    sel.innerHTML = optionHtml;
    sel.value = keep && Array.from(sel.options).some((o) => o.value === keep) ? keep : "";
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
    (p) => p.ip === r.default_proxy_ip && String(p.port) === String(r.default_proxy_port || "")
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
  await loadRobots();
}

function onRobotAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id } = btn.dataset;
  if (act === "select") selectRobot(id);
  else if (act === "start") selectRobot(id).then(startRobot);
  else if (act === "stop") post(`/api/robots/${id}/stop`).then(loadRobots);
  else if (act === "edit" && IS_ADMIN) openEdit(id);
  else if (act === "delete" && IS_ADMIN) {
    if (confirm("Delete this robot?")) post(`/api/robots/${id}/delete`).then(loadRobots);
  }
}

async function onAccountAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, label, bank } = btn.dataset;
  if (act === "ban") await toggleAccount(label, "ban");
  else if (act === "unban") await toggleAccount(label, "unban");
  else if (act === "view") await viewStatement(label, bank);
  else if (act === "remove") await removeAccount(label);
  else if (act === "next") await jumpNextAccount(label);
}

async function jumpNextAccount(label) {
  const id = state.selectedId;
  if (!id) return;
  if (!confirm(`Make "${label}" the next account to scrape (one time)?`)) return;
  setStatus(`Setting ${label} as next to scrape...`);
  try {
    const res = await post(`/api/robots/${id}/next`, { label });
    setStatus(res.error ? res.error : `${label} will be scraped next (one time).`, !!res.error);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function updateOmittedRows(label, value) {
  const id = state.selectedId;
  if (!id) return;
  try {
    const res = await post(
      `/api/robots/${id}/accounts/${encodeURIComponent(label)}/update`,
      { omitted_rows: value }
    );
    setStatus(res.error ? res.error : `Omitted rows for "${label}" saved.`, !!res.error);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadAccounts();
}

function onOmittedFocus(e) {
  const t = e.target.closest(".omitted-input");
  if (!t) return;
  state.omittedEditing = t.dataset.label;
}

function onOmittedBlur(e) {
  const t = e.target.closest(".omitted-input");
  if (!t) return;
  state.omittedEditing = null;
  const label = t.dataset.label;
  const value = t.value.trim();
  updateOmittedRows(label, value === "" ? null : value);
}

function init() {
  $("#start-btn").addEventListener("click", startRobot);
  $("#stop-btn").addEventListener("click", stopRobot);
  $("#log-refresh").addEventListener("click", loadLogIfAuto);
  $("#log-auto").addEventListener("change", (e) => {
    state.autoLog = e.target.checked;
    if (state.autoLog) loadLogIfAuto();
  });
  $("#statement-close").addEventListener("click", () => $("#statement-dialog").close());
  $("#statement-copy").addEventListener("click", copyStatement);
  wireLiveFeed();
  $("#edit-cancel").addEventListener("click", () => $("#edit-dialog").close());
  $("#edit-form").addEventListener("submit", submitEdit);
  $("#add-robot-form").addEventListener("submit", submitAdd);
  $("#robots-table tbody").addEventListener("click", onRobotAction);
  $("#accounts-table tbody").addEventListener("click", onAccountAction);
  $("#accounts-table tbody").addEventListener("focusin", onOmittedFocus);
  $("#accounts-table tbody").addEventListener("focusout", onOmittedBlur);
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".min-toggle");
    if (!t) return;
    const panel = t.closest(".panel");
    if (!panel) return;
    const collapsed = panel.classList.toggle("collapsed");
    t.textContent = collapsed ? "+" : "−";
  });
  if (!IS_ADMIN) {
    const add = document.querySelector(".add-robot");
    if (add) add.hidden = true;
  }
  loadProxyOptions();
  loadRobots();
  setInterval(loadRobots, 2500);
}

init();