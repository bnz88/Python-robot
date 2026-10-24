"use strict";

async function loadRobotOptions() {
  const robots = await get("/api/robots");
  for (const selId of ["acct-robot", "acct-edit-robot"]) {
    const sel = document.getElementById(selId);
    if (!sel) continue;
    sel.innerHTML = '<option value="">robot...</option>';
    for (const r of robots) {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${r.name} (${r.host}:${r.port})`;
      sel.appendChild(opt);
    }
  }
}

async function loadAccounts() {
  const data = await get("/api/accounts");
  renderAccounts(data.accounts || []);
  if (data.conflicts && data.conflicts.length) {
    setStatus(
      "Conflict: these labels exist on more than one robot: " + data.conflicts.join(", "),
      true
    );
  }
}

function renderAccounts(accounts) {
  const tbody = $("#accounts-table tbody");
  tbody.innerHTML = "";
  if (!Array.isArray(accounts)) return;
  for (const a of accounts) {
    const tr = document.createElement("tr");
    const last = a.last_scrape
      ? new Date(a.last_scrape * 1000).toLocaleString()
      : "-";
    let toggleBtn = "";
    if (a.enabled === false) {
      toggleBtn = `<button class="btn-unban" data-act="unban" data-id="${a.robot_id}" data-label="${esc(a.label)}">Unban</button>`;
    } else if (a.enabled === true) {
      toggleBtn = `<button class="btn-ban" data-act="ban" data-id="${a.robot_id}" data-label="${esc(a.label)}">Ban</button>`;
    }
    tr.innerHTML = `
      <td class="label-cell">${bankIcon(a.bank)}${esc(a.label)}${a.conflict ? ' <span class="warn">(conflict)</span>' : ""}</td>
      <td>${esc(a.robot_name || a.robot_id)}${a.reachable ? "" : " <span class='warn'>(offline)</span>"}</td>
      <td>${esc(a.bank || "")}</td>
      <td>${esc(a.unique_id ?? "")}</td>
      <td>${esc(a.bank_shortname ?? "")}</td>
      <td>${a.enabled === null ? "-" : a.enabled ? "yes" : "no"}</td>
      <td>${a.output_exists === null ? "-" : a.output_exists ? "yes" : "no"}</td>
      <td>${esc(last)}</td>
      <td>
        <button data-act="next" data-id="${a.robot_id}" data-label="${esc(a.label)}" title="Scrape this account next (one time)">Scrape now</button>
        <button data-act="view" data-id="${a.robot_id}" data-label="${esc(a.label)}" data-bank="${esc(a.bank || "")}">View</button>
        <button data-act="edit" data-id="${a.robot_id}" data-label="${esc(a.label)}" data-bank="${esc(a.bank || "")}" data-uid="${esc(a.unique_id ?? "")}" data-short="${esc(a.bank_shortname ?? "")}">Edit</button>
        ${toggleBtn}
        <button data-act="remove" data-id="${a.robot_id}" data-label="${esc(a.label)}">Remove</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function viewStatement(id, label, bank) {
  const data = await get(
    `/api/robots/${id}/statement/${encodeURIComponent(label)}?bank=${encodeURIComponent(bank)}`
  );
  $("#statement-body").textContent =
    data && data.text != null ? data.text : "(no output yet)";
  $("#statement-dialog").showModal();
}

async function onAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id, label, bank, uid, short } = btn.dataset;
  try {
    if (act === "view") await viewStatement(id, label, bank);
    else if (act === "edit") openAccountEdit(id, label, bank, uid, short);
    else if (act === "next") {
      if (!confirm(`Make "${label}" the next account to scrape (one time)?`)) return;
      setStatus(`Setting ${label} as next to scrape...`);
      const res = await post(`/api/robots/${id}/next`, { label });
      if (res.error) { setStatus(res.error, true); }
      else { setStatus(`${label} will be scraped next (one time).`); }
    }
    else if (act === "ban") await post(`/api/robots/${id}/accounts/${encodeURIComponent(label)}/ban`);
    else if (act === "unban") await post(`/api/robots/${id}/accounts/${encodeURIComponent(label)}/unban`);
    else if (act === "remove") {
      if (!confirm(`Remove account "${label}" from this robot?`)) return;
      setStatus("Removing account...");
      await post("/api/accounts/remove", { robot_id: id, label });
    }
    await loadAccounts();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function openAccountEdit(id, label, bank, uniqueId, shortname) {
  const form = $("#account-edit-form");
  form.dataset.currentRobot = String(id);
  form.label.value = label;
  $("#acct-edit-label").textContent = label;
  const robotSel = $("#acct-edit-robot");
  robotSel.value = String(id);
  const bankSel = form.bank;
  const firstBank = Array.from(bankSel.options).find((opt) => opt.value);
  bankSel.value = bank || (firstBank ? firstBank.value : "");
  form.unique_id.value = uniqueId || "";
  form.bank_shortname.value = shortname || "";
  form.username.value = "";
  form.password.value = "";
  $("#account-edit-dialog").showModal();
}

async function submitAccountEdit(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const robotId = fd.get("robot_id");
  const currentRobot = e.target.dataset.currentRobot;
  const label = fd.get("label");
  const bank = fd.get("bank");
  const uid = fd.get("unique_id");
  const short = fd.get("bank_shortname");
  const username = (fd.get("username") || "").trim();
  const password = fd.get("password") || "";
  setStatus("Saving account...");
  try {
    if (String(robotId) !== String(currentRobot)) {
      if (!username || !password) {
        setStatus("Username and password are required to move the account to another robot.", true);
        return;
      }
      setStatus("Moving account to another robot...");
      const removeRes = await post("/api/accounts/remove", { robot_id: currentRobot, label });
      if (removeRes.error) { setStatus(removeRes.error, true); return; }
      const addRes = await post("/api/accounts", { robot_id: robotId, label, bank, username, password, unique_id: uid, bank_shortname: short });
      if (addRes.error) { setStatus(addRes.error, true); return; }
      setStatus("Account moved.");
    } else {
      const payload = { bank, unique_id: uid, bank_shortname: short };
      if (username) payload.username = username;
      if (password) payload.password = password;
      await post(`/api/robots/${robotId}/accounts/${encodeURIComponent(label)}/update`, payload);
      setStatus("Account saved.");
    }
    $("#account-edit-dialog").close();
    await loadAccounts();
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function submitAdd(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  setStatus("Adding account...");
  try {
    const res = await post("/api/accounts", Object.fromEntries(fd.entries()));
    if (res.error) {
      setStatus(res.error, true);
      return;
    }
    setStatus("Account added.");
    e.target.reset();
    await loadAccounts();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function init() {
  $("#add-account-form").addEventListener("submit", submitAdd);
  $("#accounts-table tbody").addEventListener("click", onAction);
  $("#statement-close").addEventListener("click", () => $("#statement-dialog").close());
  $("#account-edit-cancel").addEventListener("click", () => $("#account-edit-dialog").close());
  $("#account-edit-form").addEventListener("submit", submitAccountEdit);
  loadRobotOptions();
  loadAccounts();
  setInterval(loadAccounts, 3000);
}

init();