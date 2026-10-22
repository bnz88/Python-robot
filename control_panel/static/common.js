"use strict";

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function $(sel) {
  return document.querySelector(sel);
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(url, { credentials: "same-origin", ...options, headers });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  return resp.json().catch(() => ({}));
}

function get(url) {
  return api(url);
}

function post(url, body) {
  return api(url, { method: "POST", body: body || {} });
}

async function robotAction(id, action) {
  if (action === "start") {
    return post(`/api/robots/${id}/start`, {});
  }
  return post(`/api/robots/${id}/stop`, {});
}

function setStatus(msg, isError) {
  const el = document.getElementById("status");
  if (el) {
    el.textContent = msg || "";
    el.classList.toggle("bad", !!isError);
  }
}