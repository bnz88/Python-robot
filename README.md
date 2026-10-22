# Banking Control Panel

Web control panel that manages many BCA scraper robots. Each robot automates
login to the banking sites (**KlikBCA**, **myBCA**, **CIMB**, and **PERMATA**)
using OS-level keyboard/mouse macros (PyAutoGUI), captures the statement page
text and saves it to a `.txt` file per account. No Selenium/Playwright/Puppeteer,
so no WebDriver fingerprint is exposed.

> **Manuals:** [Installation Manual](manual/INSTALLATION.md) (how to install and
> start the panel and robots) and [Operator & Admin Guide](manual/OPERATOR_ADMIN_GUIDE.md)
> (how to use the app day to day). To install with one click, double-click
> `install\install_robot.cmd` and/or `install\install_panel.cmd`.

> CIMB (`cimb`) uses an image-gated flow: it waits for the login form image
> (`assets/cimb/user_id.JPG`), clicks the user id input, types the
> username/password, waits for the logged-in image
> (`assets/cimb/cimb_logout_btn.JPG`, the logout button), navigates directly to
> the statement URL, captures the statement, then logs out via the logout image.
> If either gate image is missing the account is aborted (nothing saved, cooldown
> cleared, next account continues). Omitted-row counting is manual only via
> `cimb_omitted_rows` (no auto-detect).

> PERMATA (`permata`) flow: close the landing modal, log in (click the username
> field image, type username/password, solve the case-sensitive 4-character image
> captcha — Tesseract-first, training-free, see below). The site refreshes the
> captcha image itself after a rejected login and keeps the page, so a retry only
> clears the rejected code from the field and solves the new image — no reload and
> no refresh button; up to `permata_captcha_attempts` attempts run, a failed
> intermediate attempt waits `permata_captcha_retry_wait` (3s), and the final
> attempt waits the full `permata_dashboard_wait`, then confirm login by the
> user-icon gate (`assets/permata/user_icon.JPG`; its middle letters vary). If the
> icon is not found the account is aborted (nothing saved, cooldown cleared, next
> account). On success it opens the statement URL, finds the `ind_flag.JPG` flag —
> the page ignores the mouse wheel, so it scrolls one screen at a time with
> `PageDown` (falling back to clicking the page once and re-trying `PageDown`,
> then the wheel and arrow keys), up to `permata_scroll_max_steps` (20) times,
> and verifies the page actually moved before each probe — then
> clicks it, captures the statement, and logs out via the user icon +
> `logout_btn_permata.JPG`.
> If a logout image is not found the account is not saved (cooldown cleared, next
> account). The changed statement is then uploaded to the backoffice like the other
> banks. Omitted-row counting is manual only via `permata_omitted_rows` / the
> account's `omitted_rows`.

## Requirements

- Windows (macros drive a real Chrome window)
- Python 3.8+
- Google Chrome installed at `C:\Program Files\Google\Chrome\Application\chrome.exe`
- Tesseract OCR engine (only for PERMATA captcha OCR fallback; put it on `PATH`
  or set `permata_tesseract_cmd`). The primary OCR engine is `ddddocr`
  (installed via `pip install -r requirements.txt`).

## Install

```powershell
pip install -r requirements.txt
```

`config.json` and `control_panel/config.json` are **not** tracked (they hold live
credentials). Create them from the templates, then fill in `robot_token`, the
`backoffice` credentials and any proxy:

```powershell
Copy-Item config.example.json config.json
Copy-Item control_panel\config.example.json control_panel\config.json
```

The one-click installers in `install\` do this copy automatically when the files are
missing.

## Configure

1. Edit `accounts.json` with one entry per account:

   ```json
   [
     { "bank": "klikbca", "username": "USERID", "password": "PIN", "label": "bca_rek_utama" },
     { "bank": "mybca", "username": "USER", "password": "PASS", "label": "mybca_utama" }
   ]
   ```

   - `bank` must be `klikbca`, `mybca`, `cimb` or `permata`.
   - `label` becomes the output filename (`output/<label>.txt`); labels must be unique.
   - `accounts.json` is gitignored.

2. Adjust `config.json` if your Chrome path or timing differs. Notable keys:
   - `chrome_exe` — Chrome binary path.
   - `window_width` / `window_height` — fixed window size when `chrome_maximized` is `false` (screen resolution must fit it).
   - `chrome_maximized` — open Chrome maximized to the full screen for every bank (default `true`).
     `window_width` / `window_height` are then only a fallback for coordinates;
     reference images are matched against the real window, so recapture the assets
     (`python main.py --capture`) if a different window size breaks the matches.
   - `close_existing_chrome` — close every running Chrome on the robot machine
     before launching the scraper's browser (default `true`). Another Chrome window
     competes for the foreground and breaks the keyboard/mouse macros. Do not view
     the control panel in Chrome on the robot machine — use another PC or Edge.
   - `chrome_scale` — device scale factor for the scraper's Chrome (`1.0` = 100 %,
     `0.75` = zoomed out to 75 %). It is passed as
     `--force-device-scale-factor` and scales the page as well as the browser UI,
     so changing it requires recapturing the reference images. Useful when the
     robot desktop is smaller than the screen the assets were captured on
     (e.g. a 1024×768 console vs a 1262×770 RDP session).
   - `chrome_zoom_percent` — **page** zoom, the same thing as Ctrl + mouse wheel
     (`75` = 75 %). Applied after every navigation with Ctrl+0 and the Chrome
     presets (`25 33 50 67 75 80 90 100 110 125 150 175 200 250 300 400 500`);
     values outside the list snap to the nearest preset. The browser UI stays at
     100 %, only the page shrinks — which is usually what you want on a small
     console. Reference images must be captured at the same zoom.
   - `tabs_to_username` — number of Tab presses to reach the username field after focusing the page (1 by default; tune per site if login types into the wrong field).
   - `image_confidence` — OpenCV match threshold for the submit/menu buttons.
   - `between_accounts_wait` — seconds to wait after closing Chrome before the next account starts.
   - `account_cooldown_seconds` — minimum seconds between scrapes of the same account (180 = 3 minutes).
   - `python_exe` — python to use for `/control/start` (defaults to the interpreter running `api.py`).
   - `scraper_script` — script launched by `/control/start` (default `main.py`).
   - `stop_timeout` — seconds to wait after issuing a stop before giving up (default 20).
   - `proxy_ip` / `proxy_port` — optional default HTTP proxy for Chrome (no auth); `--proxy-ip`/`--proxy-port` passed via `/control/start` override these.
   - `mybca_logout_wait` / `mybca_logout_process_wait` — seconds to wait before clicking logout and after it, respectively.

## First-run asset capture (required)

The submit button and KlikBCA menu are located by matching saved reference PNGs.
Capture them once:

```powershell
python main.py --capture
```

For each bank the script opens the login page and pauses. Save the required images:

| File | Screen to capture |
|---|---|
| `assets/klikbca/login_button.png` | KlikBCA login submit button |
| `assets/klikbca/menu_statement.png` | Each KlikBCA menu item leading to the statement page |
| `assets/mybca/logout_button.png` | (Optional) myBCA logout button, top-right corner |
| `assets/mybca/logout_confirm.png` | (Optional) myBCA logout confirmation button |
| `assets/cimb/user_id.JPG` | CIMB login form user id input box |
| `assets/cimb/cimb_logout_btn.JPG` | CIMB logout button (also confirms the logged-in dashboard) |
| `assets/permata/logout_button.png` / `logout_btn_permata.JPG` | PERMATA logout button (in the user-icon menu) |
| `assets/permata/close_button.JPG` | PERMATA landing-page modal close button (clicked to dismiss the modal) |
| `assets/permata/user_id1.JPG` / `user_id2.JPG` | PERMATA username field label (Indonesian / English), clicked to focus the input |
| `assets/permata/captcha.JPG` | PERMATA captcha image, used to locate the captcha on screen before OCR |
| `assets/permata/user_icon.JPG` | PERMATA user icon (login gate; also opens the logout menu) — middle letters vary |
| `assets/permata/ind_flag.JPG` | PERMATA statement flag, clicked on the statement page to load the mutations |

myBCA needs no reference images to log in: its login page auto-focuses the username
field, so the script types the username, presses Tab once to the password field, types
the password, and presses Enter.

For myBCA logout, if `assets/mybca/logout_button.png` exists it is image-matched and
clicked; otherwise the script clicks the top-right corner using `mybca_logout_x` /
`mybca_logout_y` in `config.json` (defaults to `window_width - 40`, `110`). If
`assets/mybca/logout_confirm.png` exists, it clicks that to confirm.

Crop tightly around the element for reliable matching. Optional: save a
`assets/<bank>/challenge.png` of any unexpected OTP/challenge screen to enable the
graceful manual-pause fallback.

KlikBCA also uses two page-check images to confirm each screen is actually loaded
(`klikbca_landing_page`, default `landingpage.PNG`, and `klikbca_logout_button`,
default `logout_button.PNG`, which marks the dashboard). The script waits up to
`klikbca_page_timeout` seconds for each one; if it never appears the account is
stopped before anything is captured — nothing is saved, the account is not flagged as
scraped (its cooldown is cleared), and the loop moves on to the next account.

Statement-button images (`klikbca_statement_buttons`) are searched for up to
`klikbca_stmt_button_timeout` seconds each, and the match tries a few scales
(`klikbca_button_scales`, default `[1.0, 0.8, 0.67, 0.5, 1.25, 1.5]`) so a reference
saved from a screenshot taken at a different display scale still matches. The log
reports the match score; when nothing matches the best score is logged and the page is
saved to `output/debug/<label>_stmt_button.png`, then the `klikbca_stmt_fallback_tabs`
tab/Enter fallback runs.

PERMATA login needs OCR. Two engines are used: `ddddocr` (installed via
`pip install -r requirements.txt`; accurate but its bundled model emits lowercase
only) and Tesseract (case-aware; needs the Tesseract engine installed, e.g. the
Windows installer from UB Mannheim, either on `PATH` or via
`permata_tesseract_cmd`). `permata_ocr_engine` (default `auto`) prefers
Tesseract's case when both engines agree on the letters; set it to `ddddocr` or
`tesseract` to force one engine. The captcha is located by the `captcha.JPG`
reference (matched with `permata_captcha_blur` so it keys on the background, not
the changing letters); the located crop is validated against
`permata_captcha_length` (4) and `permata_captcha_charset` (case-sensitive,
includes both cases). A fixed screen region (`permata_captcha_x` / `_y` / `_w` /
`_h`) can be set as a fallback if the reference image is not found.

### Case-accurate captcha solving (no model training)

The PERMATA captcha is case-sensitive but ddddocr only emits lowercase, so
`utils/captcha.read_captcha_permata` combines two engines **without training any
model** (no GPU needed). Tesseract reads the whole string (letters *and* case)
and is markedly more accurate than ddddocr on the real captcha, so its
preprocessed read is the primary result; ddddocr supplies a lowercase letter
sequence as the fallback. When a font is known, per-glyph case is refined from,
in order:

1. **the captcha's own font** — `tools/permata_font_id.py` identifies the font
   from a small labeled set and writes `assets/permata/font.json` (only when it
   scores above the tool's threshold); at runtime each glyph is compared against
   the same character rendered in both cases and the better match wins (accepted
   when the mean margin reaches `permata_case_min_score`, default `0.05`);
2. **Tesseract's read** (letters and case);
3. **ddddocr's letters** and the plain engine consensus (`permata_ocr_engine`).

`permata_case_mode` selects `auto` (default), `font`, `tesseract` or `baseline`
(skip case resolution). The resolver never does worse than the plain consensus.

**Labeled dataset.** Put real captcha crops in `dataset/permata/images/` and label
them in `dataset/permata/labels.txt` as `<filename><TAB><text>` (exact case, e.g.
`0001.png<TAB>sf4H`). A few dozen samples is enough. Set
`permata_capture_samples` to have the scraper save every located crop; a
successful login then records its (perfectly case-labeled) text automatically.

**Offline tools** (CPU only):

```powershell
python tools/permata_font_id.py   # identify the font -> assets/permata/font.json
python tools/permata_eval.py      # case-sensitive accuracy + misses report
```

`permata_eval.py` prints case-sensitive full-string accuracy (what the bank
checks), case-insensitive letter accuracy, per-character accuracy and a confusion
report, and copies mismatches to `dataset/permata/misses/`. Use it to tune the
preprocessing variants and thresholds; re-run `permata_font_id.py` as the labeled
set grows. `permata_font_id.py` only writes `font.json` when a font matches above
its threshold (default `0.5`); `--force` overrides that, but a poorly-matched font
can *lower* accuracy — always confirm with `permata_eval.py`.

## Run

```powershell
python main.py                    # all accounts, looping forever (Ctrl+C to stop)
python main.py --account mybca    # only mybca accounts
python main.py --account klikbca  # only klikbca accounts
python main.py --account cimb     # only cimb accounts
python main.py --account permata  # only permata accounts
```

Each account runs in a fresh Chrome profile (temp `--user-data-dir`), so there is no
stale session between accounts. Statement text is captured to memory and only written
to `output/<label>.txt` (UTF-8, no BOM) after the backoffice process accepts it (or
when the backoffice is disabled, or when the statement is unchanged — the file is
then just touched to refresh the cooldown). Nothing is saved before the backoffice
upload runs. A failed upload/submit is not retried immediately: the account's
cooldown is cleared and the loop moves on to the next available account (it is only
revisited once no other account has work, backing off one cooldown period). Failed
accounts leave a debug screenshot in `output/debug/`.

By default the run loops forever. Each account may only be scraped once every
`account_cooldown_seconds` (180s = 3 minutes). The loop scans the accounts in order:
an account is scraped only if its `output/<label>.txt` is missing or older than the
cooldown; otherwise it skips to the next account. When every account is still within
its cooldown, it waits until the earliest one becomes eligible and continues.
`between_accounts_wait` (5s) is the gap after each scrape. Press `Ctrl+C` to stop.
Set `loop_forever` to `false` in `config.json` for a single pass that scrapes only the
eligible accounts.

The cooldown uses the output file's modification time, so it survives restarts.
If the logout button is not found for an account (any bank), the run is not
flagged as a scrape: nothing is saved, the account's cooldown is cleared, and
the loop simply moves on to the next account. The passed-over account is only
retried after no other account has work left (backing off one cooldown period
when nothing else is ready).

## How it works

1. Launch Chrome with a fresh profile at a fixed window size.
2. Navigate to the login URL.
3. myBCA: wait for the form, type the username (already focused), press Tab once,
   type the password, press Enter, wait for the dashboard, then open the statement URL.
   KlikBCA: wait for the landing page image, then focus the page, Tab to username ->
   type -> Tab to password -> type -> `Enter`; wait for the dashboard image (logout
   button); if `Enter` does not submit, it image-matches and clicks the submit button,
   then clicks menu images to reach the statement page. If either page-check image is
   missing the run is aborted for that account (nothing saved, cooldown cleared, next
   account continues).
4. `Ctrl+A` -> `Ctrl+C` -> read clipboard -> keep the statement text in memory.
5. myBCA: click the logout button at the top-right corner (image or coordinate).
6. Upload the changed statement to the backoffice; only after the save succeeds
   (or the upload is skipped) is `output/<label>.txt` written.

## API (statements + control)

A small HTTP server serves each account's scraped statement by label and can start
or stop the scraper. It uses only the Python standard library (no extra dependencies)
and can run alongside the scraper.

```powershell
python api.py
```

Host/port come from `config.json` (`api_host`, `api_port`; default
`127.0.0.1:8000`).

### Statements

| Request | Response |
|---|---|
| `GET /<bank>/<label>` (e.g. `GET /mybca/SYAHRUDIN992`) | `200` `text/plain` with `output/<label>.txt` |
| Missing file / unknown bank / bad path | `404` `application/json` body `null` |

### Control (start / stop the scraper)

| Request | Response |
|---|---|
| `GET\|POST /control/start[?account=mybca\|klikbca][&ip=1.2.3.4&port=8080]` | `200` `{"started":bool,"running":true,"pid":int,"message":...}` |
| `GET\|POST /control/stop` | `200` `{"stopped":bool,"running":false,"message":...}` |
| `GET /control/status` | `200` `{"running":bool,"pid":int\|null,"returncode":int\|null}` |

`/control/start` launches `python main.py` (optionally `--account <bank>`) in a new
visible console window on the desktop, so the scraper's verbose log messages are shown
as it runs. It refuses to start a second instance while one is running. `/control/stop`
force-kills the scraper's process tree (python plus any Chrome it opened), which closes
that console window and stops the script. Scraper logs live in the console window only.

Passing `ip` and `port` makes every Chrome window the scraper opens use that HTTP proxy
(`--proxy-server=http://ip:port`); no proxy username/password is used. If only one of
`ip`/`port` is supplied it is ignored.

```powershell
curl "http://127.0.0.1:8000/control/start?account=mybca&ip=1.2.3.4&port=8080"
curl "http://127.0.0.1:8000/control/start?account=mybca"
curl http://127.0.0.1:8000/control/status
curl -X POST http://127.0.0.1:8000/control/stop
curl http://127.0.0.1:8000/mybca/SYAHRUDIN992
```

## Control panel

A central Flask panel (`control_panel/`) manages many robots over the network.
Each robot runs `api.py`; the panel stores each robot's host/port/token and relays
start/stop, account listing, ban/unban, statement, and log-tail requests.

```powershell
pip install -r control_panel/requirements.txt
python control_panel/app.py   # serves http://127.0.0.1:5000 by default
```

Panel configuration lives in `control_panel/config.json` (`panel_host`,
`panel_port`, `secret_key`, `db_path`, and the seeded `admin_username` /
`admin_password`). Robots are added from the dashboard UI; each robot's token is
stored in `control_panel/panel.db` (never account credentials). The panel has
three pages: **Dashboard** (robot status + start/stop + per-robot logs),
**Accounts** (add/remove bank accounts across robots — each label is globally
unique and can belong to only one robot), **Live Logs** (one auto-refreshing
log window per robot, headed by which account is being scraped now and which is
next), and **Proxies** (manage a proxy list that is selected when adding or
editing a robot).

### Users and roles

The panel supports multiple users with two roles, stored in the `users` table of
`panel.db`:

- **admin** — full access, including the **Settings** page (per-robot
  `config.json`), the **Users** page, and adding/editing/deleting robots.
- **operator** — can run robots (start/stop/jump next), manage accounts,
  view live logs/live view, and manage proxies, but cannot open **Settings** or
  add/edit/delete robots.

Users are managed on the **Users** page (admin only) or via `/api/users`. The
configured `admin_username` is always seeded as an **admin**; new users default
to **operator**. The last remaining admin cannot be deleted or demoted, and you
cannot delete your own account.

### Robot token auth

Set `robot_token` in the robot's `config.json` to require the `X-Robot-Token`
header on every route except `GET /health`. An empty token keeps auth disabled
for local back-compat. `api_host` defaults to `0.0.0.0` so remote panels can
reach the robot.

### Additional robot endpoints

| Request | Response |
|---|---|
| `GET /health` | `200 {"ok":true}` (no auth) |
| `GET /accounts` | `200 [{label,bank,enabled,output_exists,last_scrape}]` (no passwords) |
| `POST /accounts/<label>/ban` | sets `enabled:false` in `accounts.json` |
| `POST /accounts/<label>/unban` | sets `enabled:true` in `accounts.json` |
| `GET /control/log?lines=200` | tail of `log_file` as `text/plain` |

`log_file` (default `output/scraper.log`) is written by `main.py` in addition to
the console, and truncated each time `/control/start` launches a new run.
`main.py` reloads `accounts.json` every loop iteration, so a ban/unban takes
effect live and disabled accounts are skipped.

### Accounts & backoffice upload

Each account may carry a `unique_id` (ID number) and `bank_shortname` — set them
in the panel's **Accounts** page (add or edit). After a scrape, `main.py` compares
the new statement text to the previous scrape; when it has changed, the robot
uploads it to the Sistem88 backoffice using Playwright (`backoffice.py`). Enable
and configure this under `backoffice` in `config.json` (`enabled`, `username`,
`password`, `login_url`, `parse_url`, `headless`).

```powershell
pip install playwright
python -m playwright install chromium
```

## Notes / caveats

- No 2FA/OTP is expected (plain username/password only). If a challenge screen
  appears and a `challenge.png` asset exists, the script pauses for manual completion.
- Tab order and field positions vary by site/locale; adjust `tabs_to_username` and the
  reference images if a field is filled incorrectly.
- Keep the mouse/keyboard untouched while the script runs.
- The process enables Windows DPI awareness and maps screenshot pixels to mouse
  coordinates before clicking, so display scaling (125 %/150 %) no longer shifts
  clicks. Keep scaling at 100 % where possible and use the same scaling on the
  machine that captured the reference images.
- A disconnected RDP session keeps the processes alive but stops rendering the
  desktop, which breaks screen capture and CAPTCHA OCR. Use
  `deploy\disconnect-to-console.ps1` (or its desktop shortcut) instead of closing
  the RDP window: it re-attaches the session to the console with `tscon` and then
  drops the connection, so the robot keeps working. `-DisableSleep` also turns off
  standby, the monitor timeout and the screen saver.

  ```powershell
  cd C:\Apps\python-robot\Python-robot
  .\deploy\create-disconnect-shortcut.ps1    # one-time: adds the desktop shortcut
  ```

  Never sign out or shut down the session while a run is active; that stops the
  scraper.
