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
  loadProxies();
}

init();