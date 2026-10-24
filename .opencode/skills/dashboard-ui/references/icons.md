# Dashboard icons

One icon family, one stroke. Use these inline SVGs (no CDN, no icon font).
Style is Lucide-like: 24px grid, `stroke-width: 1.75`, round caps/joins,
`currentColor`, no fill unless noted.

## Base CSS

```css
.icon {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  stroke: currentColor;
  fill: none;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.icon-sm { width: 16px; height: 16px; }
.icon-lg { width: 24px; height: 24px; }
.icon-inline { display: inline-block; vertical-align: -0.15em; }
```

Sizes: **16px** inline with text · **18–20px** in buttons · **20–24px** in nav,
stat tiles and empty states. Buttons use `display:inline-flex; gap:8px`.

## Semantic map (use these meanings everywhere)

| Meaning | Icon id | Used on |
|---|---|---|
| Dashboard | `i-dashboard` | nav |
| Activity / live | `i-activity` | nav, KPI |
| Robot | `i-robot` | robot cards, KPI |
| Start | `i-play` | Start buttons |
| Stop | `i-stop` | Stop buttons |
| Power / on-off | `i-power` | robot state |
| Refresh | `i-refresh` | log/live refresh |
| Server / host | `i-server` | robots, proxies |
| CPU / worker | `i-cpu` | KPI |
| User | `i-user` | account menu |
| Users | `i-users` | users page |
| Settings | `i-settings` | settings nav |
| Shield / security | `i-shield` | admin, users |
| Logs | `i-file-text` | logs page |
| Network / proxy | `i-wifi` | proxies |
| Add | `i-plus` | add forms |
| Delete | `i-trash` | destructive actions |
| Edit | `i-pencil` | edit actions |
| Expand | `i-chevron-down` | selects, details |
| Success | `i-check` | toasts, states |
| Close | `i-x` | dialogs |
| Warning | `i-alert` | error/empty states |
| Time | `i-clock` | last refresh |
| Search | `i-search` | filters |
| View | `i-eye` | preview |
| Copy | `i-copy` | copy buttons |
| External | `i-external` | links out |

## Snippets

```html
<!-- dashboard -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>

<!-- activity -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l2.5-7 5 14 2.5-7h4"/></svg>

<!-- play -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5z" fill="currentColor" stroke="none"/></svg>

<!-- stop -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none"/></svg>

<!-- power -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v9"/><path d="M6.4 6.4a8 8 0 1 0 11.2 0"/></svg>

<!-- refresh -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>

<!-- robot -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4"/><circle cx="12" cy="3" r="1"/><path d="M9 13h.01M15 13h.01"/><path d="M9 17h6"/></svg>

<!-- cpu -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>

<!-- server -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>

<!-- user -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.3 3.6-6 8-6s8 2.7 8 6"/></svg>

<!-- users -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3 2.9-5.5 6.5-5.5s6.5 2.5 6.5 5.5"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6"/><path d="M18.5 14.8c1.8.8 3 2.3 3 4.2"/></svg>

<!-- settings -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>

<!-- shield -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l7 3v6c0 4.5-3 7.7-7 9-4-1.3-7-4.5-7-9V6z"/><path d="m9 12 2 2 4-4"/></svg>

<!-- file-text / logs -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h8M8 9h2"/></svg>

<!-- wifi / proxy -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5 5 0 0 1 7 0"/><path d="M12 19.5h.01"/></svg>

<!-- plus -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>

<!-- trash -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/></svg>

<!-- pencil -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>

<!-- chevron-down -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>

<!-- check -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5L20 7"/></svg>

<!-- x -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>

<!-- alert -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>

<!-- clock -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>

<!-- search -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>

<!-- eye -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/></svg>

<!-- copy -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>

<!-- external-link -->
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7"/><path d="M21 3l-9 9"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
```

Note: the inline snippets above omit `stroke`, `fill`, `stroke-width`, etc.
because `.icon` supplies them. If you use an SVG without the `.icon` class,
repeat the attributes explicitly.

## Sprite option (nav / repeated icons)

For icons used many times per page, define once in
`templates/_icons.html` and include it right after `<body>`:

```html
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
  <symbol id="i-dashboard" viewBox="0 0 24 24"><!-- paths only --></symbol>
  <symbol id="i-robot" viewBox="0 0 24 24"><!-- paths only --></symbol>
</svg>
```

```html
<svg class="icon" aria-hidden="true"><use href="#i-robot"/></svg>
```

Keep `viewBox` on each `<symbol>`; put the presentation attributes on the
`.icon` class so sprites and inline icons look identical.

## Rules

- Icons are decoration: always `aria-hidden="true"`; label the button, not the SVG.
- Never use emoji, mixed filled/outline sets, or hand-drawn shapes.
- Keep the 1.75 stroke; do not scale an icon by changing `stroke-width`.
- One icon per action; if two icons seem right, pick the more literal one.
- Bank logos stay `<img class="bank-icon">` from `static/bank-icons/`.
