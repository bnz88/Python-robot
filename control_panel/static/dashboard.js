"use strict";

const LIVE_REFRESH_MS =
  Number((document.querySelector("main") || {}).dataset?.refreshMs) || 1000;

const state = {
  robots: [],
  selectedId: null,
  autoLog: true,
  proxies: [],
  accounts: [],
  omittedEditing: null,
};

async function loadRobots() {
  state.robots = await get("/api/robots");
  const stillSelected = state.robots.some(
    (r) => String(r.id) === String(state.selectedId)
  );
  if (state.selectedId && !stillSelected) {
    state.selectedId = null;
    state.accounts = [];
    $("#robot-controls").hidden = true;
    renderAccountQueue();
  }
  renderRobotPicker();
  updateSelectedMeta();
  updateDeckState();
  if (state.selectedId) await refreshSelected();
  else renderKpis();
  refreshLive();
}

function updateSelectedMeta() {
  const robot = selectedRobot();
  const name = $("#selected-name");
  const status = $("#selected-status");
  if (name) name.textContent = robot ? robot.name : "";
  if (status) {
    status.textContent = robot
      ? `now: ${robot.current_account || "-"}  |  next: ${robot.next_account || "-"}`
      : "";
  }
}

function renderRobotPicker() {
  const sel = $("#robot-picker");
  if (!sel) return;
  const keep = state.selectedId == null ? "" : String(state.selectedId);
  const html =
    '<option value="">Select a robot&hellip;</option>' +
    state.robots
      .map((r) => {
        const label = !r.online
          ? "offline"
          : r.auth_error
            ? "auth failed"
            : r.running
              ? "running"
              : "ready";
        return `<option value="${r.id}">${esc(r.name)} - ${esc(label)}</option>`;
      })
      .join("");
  if (sel.dataset.signature !== html) {
    sel.innerHTML = html;
    sel.dataset.signature = html;
  }
  const present = state.robots.some((r) => String(r.id) === keep);
  sel.value = present ? keep : "";
}

function setMetric(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function renderKpis() {
  if (!document.getElementById("kpi-online")) return;
  const total = state.robots.length;
  const online = state.robots.filter((r) => r.online).length;
  const authIssues = state.robots.filter((r) => r.auth_error).length;
  const running = state.robots.filter((r) => r.running);
  const robot = selectedRobot();
  const accounts = state.selectedId ? state.accounts || [] : [];
  const enabled = accounts.filter((a) => a.enabled !== false).length;

  setMetric("kpi-online", `${online}<small>/${total}</small>`);
  setMetric(
    "kpi-online-foot",
    total === 0
      ? "No robots configured yet"
      : authIssues
        ? `<span class="trend down">${authIssues} auth</span> needs attention`
        : `<span class="trend">${online === total ? "all" : "partial"}</span> reachable`
  );

  const active = running[0];
  setMetric("kpi-running", `${running.length}<small> running</small>`);
  setMetric(
    "kpi-running-foot",
    active
      ? `${esc(active.name)}${active.current_account ? " &middot; " + esc(active.current_account) : ""}`
      : "No scraper running"
  );

  setMetric("kpi-accounts", `${accounts.length}`);
  setMetric(
    "kpi-accounts-foot",
    !state.selectedId
      ? "Select a robot to load accounts"
      : robot && !robot.online
        ? "Robot offline - accounts unavailable"
        : `<span class="trend">${enabled} enabled</span> ${accounts.length - enabled} paused`
  );

  const next = robot && robot.next_account ? robot.next_account : null;
  setMetric(
    "kpi-next",
    next ? `<span class="kpi-next-label">${esc(next)}</span>` : "&ndash;"
  );
  setMetric(
    "kpi-next-foot",
    robot && !robot.online
      ? "Robot is offline"
      : robot && robot.running
        ? `now: ${esc(robot.current_account || "-")}`
        : robot
          ? "Robot is stopped"
          : "Select a robot to see the queue"
  );
}

function updateDeckState() {
  const badge = $("#deck-state");
  if (!badge) return;
  const robot = selectedRobot();
  if (!robot) {
    badge.className = "badge";
    badge.textContent = "idle";
  } else if (!robot.online) {
    badge.className = "badge badge-bad";
    badge.textContent = "offline";
  } else if (robot.auth_error) {
    badge.className = "badge badge-warn";
    badge.textContent = "auth failed";
  } else if (robot.running) {
    badge.className = "badge badge-ok";
    badge.textContent = "running";
  } else {
    badge.className = "badge badge-info";
    badge.textContent = "ready";
  }

  const blocked = !robot || !robot.online || !!robot.auth_error;
  const start = $("#start-btn");
  const stop = $("#stop-btn");
  if (start) {
    start.disabled = blocked || !!robot.running;
    start.title = blocked ? "Robot is offline or auth failed" : "";
  }
  if (stop) {
    stop.disabled = blocked || !robot.running;
    stop.title = blocked ? "Robot is offline or auth failed" : "";
  }
}

function syncScrapeButton() {
  const select = $("#next-account-select");
  const button = $("#next-account-btn");
  if (!select || !button) return;
  button.disabled = !state.selectedId || !select.value;
}

function renderAccountQueue() {
  const select = $("#next-account-select");
  if (!select) return;
  const keep = select.value;
  const accounts = state.selectedId ? state.accounts || [] : [];
  const html =
    '<option value="">Select an account&hellip;</option>' +
    accounts
      .filter((a) => a.enabled !== false)
      .map(
        (a) =>
          `<option value="${esc(a.label)}">${esc(a.label)}${a.bank ? " - " + esc(a.bank) : ""}</option>`
      )
      .join("");
  if (select.dataset.signature !== html) {
    select.innerHTML = html;
    select.dataset.signature = html;
  }
  if (keep && accounts.some((a) => a.label === keep)) select.value = keep;

  const hint = $("#scrape-hint");
  if (hint) {
    hint.textContent = state.selectedId
      ? accounts.length
        ? "Only enabled accounts are listed. This does not change the saved queue."
        : "No accounts available - the robot may be offline."
      : "Select a robot to see its accounts.";
  }
  syncScrapeButton();
}

async function refreshSelected() {
  if (!state.selectedId) return;
  await Promise.all([loadAccounts(), loadLogIfAuto()]);
}

async function loadAccounts() {
  const id = state.selectedId;
  if (!id) return;
  const accounts = await get(`/api/robots/${id}/accounts`);
  state.accounts = Array.isArray(accounts) ? accounts : [];
  renderAccounts(accounts);
}

function renderAccounts(accounts) {
  if (state.omittedEditing) return;
  const tbody = $("#accounts-table tbody");
  tbody.innerHTML = "";
  if (!Array.isArray(accounts)) {
    renderAccountQueue();
    renderKpis();
    return;
  }
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
      <td class="label-cell">${bankIcon(a.bank)}${esc(a.label)}</td>
      <td>${esc(a.bank || "")}</td>
      <td>${esc(a.unique_id ?? "")}</td>
      <td>${esc(a.bank_shortname ?? "")}</td>
      <td>${a.enabled ? "yes" : "no"}</td>
      <td>${a.output_exists ? "yes" : "no"}</td>
      <td>${esc(last)}</td>
      <td><input class="omitted-input" data-label="${esc(a.label)}" value="${esc(a.omitted_rows == null ? "" : a.omitted_rows)}" placeholder="auto"></td>
      <td>
        <button data-act="next" data-label="${esc(a.label)}" title="Scrape this account next (one time)">Scrape now</button>
        <button data-act="view" data-label="${esc(a.label)}" data-bank="${esc(a.bank || "")}">View</button>
        ${
          a.enabled
            ? `<button class="btn-ban" data-act="ban" data-label="${esc(a.label)}">Ban</button>`
            : `<button class="btn-unban" data-act="unban" data-label="${esc(a.label)}">Unban</button>`
        }
      </td>`;
    tbody.appendChild(tr);
  }
  renderAccountQueue();
  renderKpis();
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
  // Auto (fastest proxy per account) is the default start behaviour.
  $("#proxy-select").value = "auto";
  $("#robot-controls").hidden = false;
  $("#accounts-title").textContent = "Accounts - " + r.name;
  $("#log-title").textContent = "Log - " + r.name;
  const picker = $("#robot-picker");
  if (picker) picker.value = String(id);
  updateSelectedMeta();
  updateDeckState();
  await refreshSelected();
}

function clearSelection() {
  state.selectedId = null;
  state.accounts = [];
  const controls = $("#robot-controls");
  if (controls) controls.hidden = true;
  const tbody = $("#accounts-table tbody");
  if (tbody) tbody.innerHTML = "";
  const log = $("#log-pane");
  if (log) log.textContent = "Select a robot to see its log.";
  const live = $("#live-panel");
  if (live) live.hidden = true;
  const modal = $("#live-modal");
  if (modal && modal.open) modal.close();
  const picker = $("#robot-picker");
  if (picker) picker.value = "";
  const selectedName = $("#selected-name");
  if (selectedName) selectedName.textContent = "";
  const selectedStatus = $("#selected-status");
  if (selectedStatus) selectedStatus.textContent = "";
  renderAccountQueue();
  renderRobotPicker();
  updateDeckState();
  renderKpis();
}

async function startRobot() {
  const id = state.selectedId;
  if (!id) return;
  const proxyChoice = $("#proxy-select").value;
  const body = { account: $("#account-select").value };
  if (proxyChoice === "auto") {
    body.proxy = "auto";
    body.proxies = (state.proxies || []).map((p) => ({
      ip: p.ip,
      port: p.port,
    }));
  } else if (proxyChoice) {
    const proxy = (state.proxies || []).find(
      (p) => String(p.id) === String(proxyChoice)
    );
    body.proxy = "manual";
    body.proxy_ip = proxy ? proxy.ip : "";
    body.proxy_port = proxy ? String(proxy.port) : "";
  }
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
  const proxyOptions = (state.proxies || [])
    .map(
      (p) =>
        `<option value="${p.id}">${esc(String(p.ip) + ":" + String(p.port))}${p.note ? " (" + esc(p.note) + ")" : ""}</option>`
    )
    .join("");
  const sel = $("#proxy-select");
  if (!sel) return;
  // Start-time choice: Auto (fastest proxy per account) is the default; there
  // is intentionally no "none" option - the scraper always uses a proxy.
  const keep = sel.value;
  sel.innerHTML =
    '<option value="auto">Auto (fastest proxy)</option>' + proxyOptions;
  const present = Array.from(sel.options).some((o) => o.value === keep);
  sel.value = keep && present ? keep : "auto";
}

async function onAccountAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, label, bank } = btn.dataset;
  if (act === "ban") await toggleAccount(label, "ban");
  else if (act === "unban") await toggleAccount(label, "unban");
  else if (act === "view") await viewStatement(label, bank);
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

  const robotPicker = $("#robot-picker");
  if (robotPicker) {
    robotPicker.addEventListener("change", (e) => {
      const value = e.target.value;
      if (value) selectRobot(value);
      else clearSelection();
    });
  }
  const nextSelect = $("#next-account-select");
  if (nextSelect) nextSelect.addEventListener("change", syncScrapeButton);
  const nextBtn = $("#next-account-btn");
  if (nextBtn) {
    nextBtn.addEventListener("click", async () => {
      if (!state.selectedId) {
        setStatus("Select a robot first.", true);
        return;
      }
      const label = nextSelect ? nextSelect.value : "";
      if (!label) {
        setStatus("Choose an account to scrape now.", true);
        return;
      }
      await jumpNextAccount(label);
      syncScrapeButton();
    });
  }
  renderAccountQueue();
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
  loadProxyOptions();
  loadRobots();
  setInterval(loadRobots, 2500);
}

init();
