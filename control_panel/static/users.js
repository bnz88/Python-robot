"use strict";

const SELF_ID = window.PANEL_USER_ID;

async function loadUsers() {
  const users = await get("/api/users");
  renderUsers(users);
}

function renderUsers(users) {
  const tbody = $("#users-table tbody");
  tbody.innerHTML = "";
  if (!Array.isArray(users)) return;
  for (const u of users) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(u.username)}${String(u.id) === String(SELF_ID) ? " (you)" : ""}</td>
      <td>
        <select data-role-for="${u.id}">
          <option value="operator"${u.role === "operator" ? " selected" : ""}>operator</option>
          <option value="admin"${u.role === "admin" ? " selected" : ""}>admin</option>
        </select>
      </td>
      <td>
        <button data-act="save-role" data-id="${u.id}" data-username="${esc(u.username)}">Save role</button>
        <button data-act="reset-password" data-id="${u.id}" data-username="${esc(u.username)}">Reset password</button>
        <button data-act="delete" data-id="${u.id}" data-username="${esc(u.username)}">Delete</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function saveRole(id, username) {
  const sel = document.querySelector(`select[data-role-for="${id}"]`);
  if (!sel) return;
  setStatus(`Updating ${username}...`);
  try {
    const res = await post(`/api/users/${id}/update`, { role: sel.value });
    setStatus(res.error ? res.error : `Role for ${username} saved.`, !!res.error);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadUsers();
}

async function resetPassword(id, username) {
  const password = prompt(`New password for "${username}":`);
  if (password == null) return;
  if (!password) {
    setStatus("Password cannot be empty.", true);
    return;
  }
  setStatus(`Resetting password for ${username}...`);
  try {
    const res = await post(`/api/users/${id}/update`, { password });
    setStatus(res.error ? res.error : `Password for ${username} updated.`, !!res.error);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function removeUser(id, username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  setStatus(`Deleting ${username}...`);
  try {
    const res = await post(`/api/users/${id}/delete`);
    setStatus(res.error ? res.error : `User ${username} deleted.`, !!res.error);
  } catch (err) {
    setStatus(err.message, true);
  }
  await loadUsers();
}

function onAction(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id, username } = btn.dataset;
  if (act === "save-role") saveRole(id, username);
  else if (act === "reset-password") resetPassword(id, username);
  else if (act === "delete") removeUser(id, username);
}

async function submitAdd(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  setStatus("Adding user...");
  try {
    const res = await post("/api/users", Object.fromEntries(fd.entries()));
    if (res.error) {
      setStatus(res.error, true);
      return;
    }
    setStatus("User added.");
    e.target.reset();
    await loadUsers();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function init() {
  $("#add-user-form").addEventListener("submit", submitAdd);
  $("#users-table tbody").addEventListener("click", onAction);
  loadUsers();
}

init();
