---
name: dashboard-ui
description: "Use for any visual or UX change to the banking control panel: modern dashboard cards, KPI stats, icons, buttons, inputs, tables, badges, modals, dark-theme polish, spacing, typography, empty/loading states, and responsive layout. Applies to control_panel/templates/*.html, control_panel/static/style.css, and the JS-rendered states of dashboard, accounts, logs, live, proxies, settings, users and login."
---

# Dashboard UI — modern dark SaaS

Goal: make the control panel look and feel like a polished modern SaaS product
(Linear / Vercel / Stripe quality) **without changing how it works**.

This is a bank-robot operations tool: clarity, status legibility and fast
scanning matter more than decoration. "Beautiful" means confident spacing,
consistent tokens, soft depth, and obvious affordances — not gradients
everywhere.

## When this applies

- "Make the dashboard prettier / more modern", "better cards / icons / buttons".
- Any edit to `control_panel/templates/`, `control_panel/static/style.css`, or
  the markup produced by `control_panel/static/*.js`.
- Not for backend, API, database or scraper changes.

## Non-negotiables (repo constraints)

- Stack: **Flask + Jinja + vanilla JS + one stylesheet**. No build step, no
  Tailwind/React/Bootstrap, no CDN, no web fonts. It must work fully offline on
  the Windows VM.
- All styling goes in `control_panel/static/style.css`. Start from the tokens in
  `references/design-tokens.css` (it keeps the legacy variable names so existing
  rules keep working). Add tokens instead of hard-coding colors.
- **Preserve every JS/Markup contract.** Never rename or remove these without
  updating the matching JS:
  - `#status`, `#robots-table` (`tbody` rows), `.proxy-select`, `.add-robot`
  - `#robot-controls`, `#selected-name`, `#selected-status`, `#proxy-select`,
    `#account-select`, `#start-btn`, `#stop-btn`
  - `#log-grid`, `.log-card`, `.log-card-head`, `.log-card-title`,
    `.log-card-status`, `.log-card-acc`, `.log-card-body`,
    `button[data-act="start"|"stop"]`
  - `#live-panel`, `#live-grid`, `.live-card`, `.live-card-img`,
    `.live-placeholder`, `#live-modal`, `.live-modal-head`
  - `#test-results`, `td.cell-ok`, `td.cell-bad`
  - `.tabs`, `.tab`, `.tab-body`, `.tab-panel`, `select[data-role-for]`
  - `#statement-body`, `#statement-close`, `#statement-copy`
  - `#add-robot-form`, `#add-account-form`, `#add-user-form`, `#add-proxy-form`,
    `#edit-form`, `#account-edit-form`, `#edit-dialog`, `#account-edit-dialog`
  - State classes toggled by JS: `.collapsed`, `.selected`, `.copied`,
    `.row-current`, `.row-next`, `.bad`
- Before changing any selector, grep for it:

  ```powershell
  Select-String -Path control_panel\static\*.js -Pattern '<selector>'
  ```

  If a JS file references it, keep the hook (add a wrapper class for styling
  instead of renaming).
- Keep Jinja loops, conditionals and server data intact. Do not move logic into
  JS. Tables are filled by JS: keep the `<thead>`/`<tbody>` contract.
- Bank logos stay `<img class="bank-icon" ... alt="...">`.
- Dark theme only. Do not add a light mode or a theme toggle.
- Never use `innerHTML` for styling changes; add classes instead.

## Design language

**Surfaces (elevation, not borders everywhere)**

- Page `--bg` → cards `--surface-1` → insets/inputs `--surface-2` →
  hover/selected `--surface-3`.
- One 1px hairline border (`--border`) plus a soft shadow (`--shadow-1` or
  `--shadow-2`). Do not stack borders and heavy shadows.
- Optional "top light" on hero cards:
  `background-image: linear-gradient(180deg, rgba(255,255,255,.04), transparent 40%)`.

**Accent & status**

- Primary accent `--accent` (blue) is for primary actions, active nav, focus.
- Use status tokens only (`--ok`, `--warn`, `--bad`, `--info`) with their soft
  tints (`--ok-soft`, …) for badges and dots.
- Never encode meaning by color alone: pair a dot/badge with text.

**Type**

- UI font: `--font-sans` (Segoe UI stack), mono only for logs/statements.
- Labels: 12px, `--muted`, `letter-spacing: .02em`.
- Card titles: 15–16px / 600. KPI values: 26–30px / 700, `font-variant-numeric: tabular-nums`.
- Body: 13–14px, line-height 1.45–1.6.

**Spacing, radius, motion**

- Spacing on the 4px scale (`--space-1` … `--space-8`). Cards pad 16–20px.
- Radii: 8 (small controls), 12 (inputs/buttons), 16 (cards), 999 (pills).
  Pick one per role and don't mix.
- Transitions 150–200ms `ease`; animate `background-color`, `border-color`,
  `box-shadow`, `transform`, `opacity` only — never `width/height/top/left`.
- Respect `@media (prefers-reduced-motion: reduce)`.

**Focus & accessibility**

- Every interactive element needs a visible `:focus-visible` ring:
  `outline: 2px solid var(--accent-ring); outline-offset: 2px;`.
- Text contrast ≥ 4.5:1 on its background. `--muted` is for secondary text,
  never for critical values.
- Icon-only buttons require `aria-label` + `title`; decorative SVGs get
  `aria-hidden="true"`.
- Use `aria-live="polite"` for `#status` updates and keep the text short.

## Layout skeleton

- Sticky topbar (blur + border-bottom), brand left, nav center/left as pills,
  user + logout right. Height ~56–64px.
- Page `<main>`: `max-width: 1280–1400px`, centered, `padding: 24px`,
  `display: flex; flex-direction: column; gap: 20px`.
- Section header pattern: title (16px/600) + optional subtitle (`--muted`) on
  the left, actions on the right.
- KPI row: `display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px;`.
- Card grids: `repeat(auto-fill, minmax(320px, 1fr))` for robot/log cards;
  `minmax(420px, 1fr)` for live frames.
- Breakpoints: 1100px (reduce columns), 720px (stack controls, table → cards),
  420px (single column, full-width buttons).
- No horizontal scrolling at 390px. Tables below 720px become stacked cards via
  `display: block` on `tr`/`td` with `data-label` attributes in the JS-rendered
  markup — preserve the table wrapper and add the attributes.
- Do not hide information on mobile; reflow it.

## Components (structure, not bloat)

**Stat / KPI card**

```
<article class="stat-card">
  <div class="stat-icon" aria-hidden="true"><svg …/></div>
  <div class="stat-body">
    <span class="stat-label">Robots online</span>
    <strong class="stat-value">3<span class="stat-total">/4</span></strong>
    <span class="badge badge-ok">All healthy</span>
  </div>
</article>
```
Icon tile: 36–40px, radius 10, `background: var(--accent-soft)`, icon 20px.
Card: `--surface-1`, 1px border, radius 16, `--shadow-1`, pad 18px.

**Robot card** (preferred over a dense table on the dashboard)

- Header: robot icon + name (600), host pill (`--surface-2`, mono 12px).
- Body: status dot + label, current/next account, PID muted.
- Footer: Start (primary) / Stop (ghost-danger) + icon actions, right-aligned.
- Selected state: 2px `--accent` ring + `--accent-soft` header, but keep text
  readable. The `.selected` row class is used by JS; style it, don't replace it.

**Buttons**

- Height 40px (32px compact, 36px in tables), radius 12, 13–14px/600.
- Primary: accent background, subtle gradient + inner highlight, white text.
- Secondary: `--surface-2` + border; ghost: transparent + border.
- Danger: `--bad`; destructive confirmations only.
- Hover: lighten surface / raise shadow; Active: `transform: translateY(1px)`.
- Disabled: 45% opacity, `cursor: not-allowed`, no hover lift.
- Icon buttons: 36×36, centered, `aria-label`; maintain the existing
  `.icon-btn` and `.icon-btn.copied` behavior.
- Keep existing button classes working (`.primary`, `.btn-ban`, `.btn-unban`,
  `.min-toggle`, `.live-zoom`).

**Inputs / selects**

- Height 40px, radius 12, `--surface-2`, 1px border, 13–14px text, 12px
  placeholder `--muted`.
- Label above field (12px muted) or the existing left label in `.field .fl`.
  Keep the `.field` layout used by settings/accounts.
- Focus: accent border + 3px soft ring (`box-shadow: 0 0 0 3px var(--accent-ring)`).
- Error: `--bad` border + helper text; never color-only.
- Custom select chevron via a background SVG data-URI; keep native `<select>`.
  Keep `.proxy-select` functional (JS fills options).
- Checkboxes/switches: 18px, accent when checked; keep native input for a11y.

**Tables**

- Wrap in `.table-card` (`overflow: auto`, radius 16, border). Sticky header
  (`position: sticky; top: 0; background: var(--surface-1)`).
- Header 12px uppercase muted; rows 44–48px; hairline row separators.
- Row hover `--surface-2`; keep `tr.selected`, `.row-current`, `.row-next`.
- Numeric cells right-aligned + `tabular-nums`.
- Empty state inside the table: icon + short message + primary action.

**Badges / pills**

- 11–12px/600, radius 999, padding 3px 8px.
- Variants: `.badge-ok/.warn/.bad/.info/.neutral` using soft tint + matching
  text/dot. Status pills get a 6px dot.

**Tabs / segmented control**

- Keep `.tabs`, `.tab`, `.tab.active`, `.tab-panel.active` hooks.
- Modern look: segmented container `--surface-2`, radius 12, 4px padding;
  active tab = `--surface-1` + shadow (or underline if space is tight).

**Dialogs**

- Keep native `<dialog>` and `::backdrop` (blur + dim).
- Radius 16, max-width 560px, header/body/footer with 20px padding,
  sticky footer actions, close icon top-right with `aria-label`.

**Logs / statements**

- Mono 12px, `--surface-0` background, radius 12, line-height 1.55.
- Add severity color via prefixes already present in text (OK/ABORT/FAIL) with
  a left accent bar or colored keyword; never reflow the text.
- Keep `white-space: pre-wrap; word-break: break-word;` and the scroll area.

**Toasts / status**

- `#status` is the global status line: give it a card-like inline style with an
  icon slot and `aria-live="polite"`. Do not turn it into a floating toast that
  overlays controls.

**Loading / empty**

- Skeleton blocks with a subtle shimmer (disable under reduced motion).
- Empty states: 20px muted icon, one sentence, one action.
- Never leave a blank white/black rectangle where a frame or card should be.

## Icons

Use `references/icons.md`: 24px grid, `stroke-width: 1.75`, `stroke="currentColor"`,
`fill="none"`, `stroke-linecap="round"`, `stroke-linejoin="round"`,
`aria-hidden="true"` (plus `aria-label` on the button, not the SVG).

- 16px inline with text, 18–20px in buttons, 20–24px in nav/stat tiles.
- Use the semantic mapping in `references/icons.md` (robot, power, activity,
  server, user, settings, shield, logs, wifi, refresh…). Do not invent a new
  icon style halfway through.
- No emoji as icons. Bank logos stay as images.
- If an icon repeats in nav, prefer a Jinja macro or an SVG sprite with
  `<symbol>`/`<use>`; otherwise inline is fine.
- Optical alignment: `vertical-align: -0.15em` for inline icons; `flex` +
  `gap: 8px` in buttons.

## Page-by-page direction

| Page | Direction |
|---|---|
| `dashboard.html` | KPI row first (robots online, running, accounts, last refresh), then robot cards with Start/Stop. Keep the selected-robot controls as a prominent card with a status summary. Keep `#robots-table` working. |
| `accounts.html` | Bank logo + label cell, status badge, omitted-rows input, ban/unban as clear pill buttons. Add a filter/search bar above the table. |
| `logs.html` | Card grid per robot (`#log-grid`); header shows status pill + actions; body is a terminal-like inset with severity accents. Keep `#log-lines`, `#log-auto`, `#log-refresh`. |
| `live.html` | Cards with 16:10 frames, placeholder icon/text, status pill, zoom button. Keep `#live-modal` and the JS-injected `.live-card-img`/`.live-placeholder`. |
| `proxies.html` | Latency matrix with sticky first column, green/red cells (`.cell-ok`/`.cell-bad`) plus icons, and a legend. |
| `settings.html` | Segmented tabs + `.field-grid`; group related settings into cards with short descriptions. Sticky save bar at the bottom of the active tab. Keep all `#settings-*` ids generated by `settings.js`. |
| `users.html` | Table with role badges (admin = accent, user = neutral), inline edit/delete icon buttons with labels. |
| `login.html` | Centered card on a soft radial gradient, brand mark, 44px inputs, full-width primary button, clear error banner. |
| `_header.html` | Sticky blurred topbar, icon+label nav pills, active state, role badge, logout as a ghost button. Add icons via inline SVG or a Jinja macro. |

## Workflow

1. **Inventory first.** Read the page template and its JS file. List the ids,
   classes, `data-*` attributes and states you must preserve. Grep before
   renaming.
2. **Tokens first.** Apply the `:root` block from `references/design-tokens.css`
   (or merge new tokens into the existing `:root`). Fix global element styles
   (`body`, `button`, `input`, `table`, `main`, `.panel`) before touching
   individual pages.
3. **Components second.** Build/reuse `.stat-card`, `.card`, `.badge`, `.btn`,
   `.table-card`, `.empty-state`, `.skeleton` in `style.css`.
4. **Pages one at a time.** Keep the DOM contracts; add wrapper classes rather
   than restructure JS-rendered elements. Keep diffs reviewable.
5. **Verify visually.**
   - Run: `python control_panel\app.py` (or the panel launcher).
   - Check every page: dashboard, accounts, logs, live, proxies, settings,
     users, login.
   - Check with data: 0 robots, 1 robot, many robots; running vs stopped;
     long account labels; empty log/live; error status.
   - Check widths 1440 / 1024 / 768 / 390; no horizontal scroll.
   - Tab through every form and button; focus must be visible.
   - Browser console must be clean.
6. **Report** what changed per page and any hooks intentionally preserved.

## Definition of done

- [ ] Every page uses only tokens from `:root` (no new hard-coded colors).
- [ ] One consistent radius scale, one shadow scale, one spacing rhythm.
- [ ] All existing JS hooks/ids still present and functional.
- [ ] Status is readable without relying on color alone.
- [ ] Contrast ≥ 4.5:1 for body text and labels.
- [ ] Visible `:focus-visible` on all interactive elements.
- [ ] No layout shift on hover; transitions ≤ 200ms; reduced-motion respected.
- [ ] Usable at 390px with no horizontal scroll.
- [ ] Loading, empty and error states designed for tables, cards and logs.
- [ ] Works offline: no CDN, no remote fonts, no new runtime dependency.
- [ ] `python control_panel\app.py` starts and all pages load without console errors.

## Anti-patterns (do not ship)

- Pure black (`#000`) surfaces, neon glows, or 5 different accent colors.
- Emoji as UI icons; mixing filled and outline icon sets; inconsistent stroke.
- Giant hero sections or decorative illustrations in an operations dashboard.
- Cards inside cards with borders on every level.
- Animating `width`, `height`, `top`/`left`, or using transitions > 250ms.
- Hiding critical data on mobile instead of reflowing it.
- Inline `style=""`, `!important` wars, or duplicating component CSS per page.
- Changing JS logic to make the UI look right.
