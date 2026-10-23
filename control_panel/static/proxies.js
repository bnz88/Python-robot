"use strict";

async function loadProxies() {
  const proxies = await get("/api/proxies");
  renderProxies(proxies);
}

function renderProxies(proxies) {
  const tbody = $("#proxies-table tbody");
  tbody.innerHTML = "";
  if (!Array.isArray(proxies)) return;
  for (const p of proxies) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(p.ip)}</td>
      <td>${esc(String(p.port))}</td>
      <td>${esc(p.note || "")}</td>
      <td><button data-act="remove" data-id="${p.id}" data-label="${esc(String(p.ip) + ":" + String(p.port))}">Remove</button></td>`;
    tbody.appendChild(tr);
  }
}

async function loadRobots() {
  const robots = await get("/api/robots");
  const select = $("#test-robot");
  const keep = select.value;
  const list = Array.isArray(robots) ? robots : [];
  select.innerHTML = list
    .map(
      (r) =>
        `<option value="${r.id}">${esc(r.name)} (${esc(r.host)}:${esc(String(r.port))})${r.online ? "" : " - offline"}</option>`
    )
    .join("");
  if (keep && Array.from(select.options).some((o) => o.value === keep)) {
    select.value = keep;
  }
  $("#test-run").disabled = list.length === 0;
}

function renderResults(data) {
  const table = $("#test-results");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  const banks = data.banks || [];
  thead.innerHTML = `<tr><th>Proxy</th>${banks
    .map((b) => `<th>${esc(b.label)}</th>`)
    .join("")}</tr>`;
  tbody.innerHTML = "";
  for (const proxy of data.proxies || []) {
    const tr = document.createElement("tr");
    const cells = banks
      .map((bank) => {
        const cell = (proxy.results || {})[bank.key] || {
          ok: false,
          error: "no result",
        };
        const good = cell.ok && !cell.slow;
        const text = cell.ok
          ? `${cell.latency_ms} ms`
          : cell.error || "failed";
        return `<td class="${good ? "cell-ok" : "cell-bad"}">${esc(text)}</td>`;
      })
      .join("");
    tr.innerHTML = `<td>${esc(proxy.host)}</td>${cells}`;
    tbody.appendChild(tr);
  }
  table.hidden = false;
}

async function runTest() {
  const robotId = $("#test-robot").value;
  if (!robotId) {
    setStatus("Add a robot first.", true);
    return;
  }
  const button = $("#test-run");
  button.disabled = true;
  setStatus("Testing proxies - this can take a few seconds...");
  try {
    const data = await post("/api/proxies/test", { robot_id: robotId });
    if (data && data.error) {
      setStatus(data.error, true);
      return;
    }
    renderResults(data);
    setStatus(`Test finished (slow above ${data.threshold_ms} ms).`);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    button.disabled = false;
  }
}

async function onAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id, label } = btn.dataset;
  if (act !== "remove") return;
  if (!confirm(`Remove proxy ${label}?`)) return;
  setStatus("Removing proxy...");
  try {
    await post(`/api/proxies/${id}/delete`);
    setStatus("Proxy removed.");
    await loadProxies();
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function submitAdd(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  setStatus("Adding proxy...");
  try {
    const res = await post("/api/proxies", Object.fromEntries(fd.entries()));
    if (res.error) {
      setStatus(res.error, true);
      return;
    }
    setStatus("Proxy added.");
    e.target.reset();
    await loadProxies();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function init() {
  $("#add-proxy-form").addEventListener("submit", submitAdd);
  $("#proxies-table tbody").addEventListener("click", onAction);
  $("#test-run").addEventListener("click", runTest);
  loadProxies();
  loadRobots();
}

init();
