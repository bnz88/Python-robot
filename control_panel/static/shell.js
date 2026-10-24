"use strict";

/* App shell: collapsible sidebar, mobile drawer, page refresh and clock.
   Kept in its own scope so it never clashes with page scripts. */
(function () {
  const app = document.getElementById("app");
  const sidebar = document.getElementById("sidebar");
  const collapseBtn = document.getElementById("sidebar-collapse");
  const menuBtn = document.getElementById("menu-toggle");
  const scrim = document.getElementById("sidebar-scrim");
  const STORAGE_KEY = "bca-sidebar-collapsed";

  function setCollapsed(collapsed, persist) {
    if (!app) return;
    app.classList.toggle("collapsed", collapsed);
    if (collapseBtn) {
      collapseBtn.setAttribute("aria-expanded", String(!collapsed));
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      collapseBtn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
    }
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
      } catch (err) {
        /* private mode / storage disabled: session only */
      }
    }
  }

  if (app) {
    let stored = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      stored = null;
    }
    if (stored === "1") setCollapsed(true, false);
  }

  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      setCollapsed(!app.classList.contains("collapsed"), true);
    });
  }

  function setMobileOpen(open) {
    if (!app) return;
    app.classList.toggle("mobile-nav-open", open);
    if (scrim) scrim.hidden = !open;
    if (menuBtn) {
      menuBtn.setAttribute("aria-expanded", String(open));
      menuBtn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      menuBtn.title = open ? "Close menu" : "Open menu";
    }
    document.body.classList.toggle("nav-open", open);
  }

  if (menuBtn) {
    menuBtn.addEventListener("click", () => {
      setMobileOpen(!app.classList.contains("mobile-nav-open"));
    });
  }
  if (scrim) scrim.addEventListener("click", () => setMobileOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setMobileOpen(false);
  });
  if (sidebar) {
    sidebar.addEventListener("click", (event) => {
      if (event.target.closest("a") && window.matchMedia("(max-width: 760px)").matches) {
        setMobileOpen(false);
      }
    });
  }

  const refresh = document.getElementById("page-refresh");
  if (refresh) {
    refresh.addEventListener("click", () => window.location.reload());
  }

  const clock = document.getElementById("top-clock");
  if (clock) {
    const text = clock.querySelector("span");
    const tick = () => {
      const now = new Date();
      const value = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      if (text) text.textContent = value;
      clock.title = "Local time " + value;
    };
    tick();
    window.setInterval(tick, 15000);
  }
})();
