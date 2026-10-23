# Banking Robot — Operator & Admin Guide

This guide explains how to **use** the Control Panel day to day: running robots,
managing accounts, and (for admins) changing settings and users.

> Installing the system is a separate document: [Installation Manual](INSTALLATION.md).

---

## 1. Who can do what

The panel has two roles. Your role is shown in the top-right corner next to your
name.

| Action | **Admin** | **Operator** |
|---|:--:|:--:|
| View Dashboard, Live Logs, Live, Accounts, Proxies | ✅ | ✅ |
| Start / Stop robots, Jump Next, Ban / Unban, View statement | ✅ | ✅ |
| Add / Edit / Remove accounts | ✅ | ✅ |
| Add / Edit / Delete proxies | ✅ | ✅ |
| Run the proxy connection test | ✅ | ✅ |
| Add / Edit / Delete **robots** | ✅ | ❌ |
| Open the **Settings** page | ✅ | ❌ |
| Open the **Users** page | ✅ | ❌ |

Operators simply do not see the Settings/Users links, and the Add-row/Edit/Delete
buttons for robots are hidden.

---

## 2. Signing in and out

1. Open the panel in a browser, e.g. `http://127.0.0.1:5000`.
2. Enter your **username** and **password**, then click **Log in**.

> The default admin is `admin` / `123456`. **Change it immediately** (see
> *Users page*).

To sign out, click **Log out** in the top-right corner.

The top bar shows the navigation links for your role and, on the right,
`signed in as <name> <role>`. The current page is highlighted.

---

## 3. Dashboard

The Dashboard is the main working screen. It has four parts.

### 3.1 Robot list

| Column | Meaning |
|---|---|
| Name | The robot's label |
| Address | `host:port` of the robot server |
| Status | `offline`, `online`, or `auth failed` |
| Running | Whether the scraper is currently running |
| PID | Process id of the running scraper |
| Proxy | The robot's default proxy, if set |
| Actions | Buttons below |

Buttons in the Actions column:

| Button | What it does |
|---|---|
| **Select** | Activates this robot (shows its controls, accounts and log below) |
| **Start** | Starts scraping (opens a Chrome window on the robot) |
| **Stop** | Stops the scraper and closes its Chrome window |
| **Edit** | (Admin) Change the robot's Name/Host/Port/Token/Proxy |
| **Delete** | (Admin) Remove the robot from the panel |

The list refreshes automatically every few seconds.

### 3.2 Add robot (admin only)

Expand **Add robot** and fill in Name, Host, Port, Token and an optional Proxy, then
click **Add**. Use the robot's IP address as Host if it runs on another computer.
The Token must match `robot_token` in the robot's `config.json`.

### 3.3 Selected robot controls

After clicking **Select**, you get:

- **Proxy** — pick a proxy for this run (or *none* to use the robot's default).
- **Account** — run *all* accounts, or only one bank (`mybca`, `klikbca`, `cimb`,
  `permata`).
- **Start** / **Stop** buttons.
- A status line showing the **current** account being scraped and the **next** one.

### 3.4 Accounts table (for the selected robot)

| Column | Meaning |
|---|---|
| Label | The account name (also the output filename) |
| Bank | `mybca`, `klikbca`, `cimb`, or `permata` |
| Unique ID / Shortname | Data sent to the backoffice |
| Enabled | `yes` / `no` (a banned account is `no`) |
| Output | Whether a statement file exists yet |
| Last scrape | When it last produced a statement |
| Omitted | See §3.5 |
| Actions | Buttons below |

Account action buttons:

| Button | What it does |
|---|---|
| **Jump Next** | Scrape this account next, once (a one-time priority) |
| **View** | Show the last saved statement text |
| **Ban** | Temporarily disable the account (kept, but skipped) |
| **Unban** | Re-enable a banned account |
| **Remove** | Delete the account from this robot |

### 3.5 Omitted rows

The **Omitted** box controls the extra `x N` line sent to the backoffice for an
account. Leave it blank for **auto** (the default behaviour, shown as a grey
`auto` hint), or type a number to force a value. It saves when you click away.

> This value is **only** appended to the backoffice upload. It is never written into
> the account's `.txt` file.

### 3.6 Log panel

Shows the live log for the selected robot. Use **Refresh** to update now, change the
number of **lines**, or tick **auto** to keep it updating automatically.

---

## 4. Accounts page

A single place to manage every account across every robot.

- The list refreshes automatically (about every 3 seconds).
- If the same **Label** exists on more than one robot, a warning appears at the top —
  labels must be unique.

### 4.1 Add an account

Fill in **Robot**, **Bank**, **Label**, **Unique ID**, **Shortname**, **Username**,
**Password**, then click **Add**.

- The robot must be **online** for the account to be saved.
- **Label** becomes the output file name and must be unique across all robots.

### 4.2 Edit an account

Click **Edit** on a row. You can change Bank, Unique ID and Shortname at any time.
Leave **Username**/**Password** blank to keep the current values.

To **move** the account to another robot, change the **Robot** dropdown. Because the
credentials are stored per robot, you must also enter the **Username** and **Password**
to move it.

### 4.3 Other buttons

| Button | What it does |
|---|---|
| **Jump Next** | Scrape this account next, once |
| **View** | Show the last saved statement |
| **Ban** / **Unban** | Disable / re-enable without deleting |
| **Remove** | Delete the account |

---

## 5. Live Logs

Shows one auto-refreshing log window per robot, each headed by the account being
scraped now and the one queued next. Useful to watch several robots at once. Use the
line-count box on the Dashboard (or the per-page control) to change how much is shown.

---

## 6. Live (screen view)

Shows the **actual screen** of each robot as a near-live image. Handy to confirm the
robot is on the right page.

> The screen feed must be enabled on the robot (`live_capture` = on in Settings →
> General). It refreshes about once per second.

---

## 7. Proxies

Manage a reusable list of proxies (IP, Port, Note).

- **Add**: fill IP, Port and an optional Note, click **Add**.
- **Remove**: delete a proxy from the list.
- On the Dashboard (or when adding/editing a robot) pick a proxy from the **Proxy**
  dropdown to use it for that run.
- **Test Connection**: pick a **Robot**, then click **Test Connection**. The robot
  measures its own latency to every bank login page through every proxy and the
  result table shows milliseconds per proxy × bank. Green = the proxy reached the
  page within the slow threshold (`proxy_test_slow_ms`, Settings → General,
  default 1000 ms); red = too slow, timed out or could not connect. The test runs
  on the selected robot, so it reflects that robot's network path.

---

## 8. Settings (admin only)

The Settings page shows **one card per robot**. Settings are sent to that robot and
saved into its `config.json`.

- Pick a **tab** to edit a group of settings.
- Change values and click **Save changes**. **Reload** re-reads the current values.
- Changes take effect the **next time the robot starts**.
- **Password fields** are write-only: they appear blank; leave them blank to keep the
  current value, or type a new one to replace it.

Tabs:

| Tab | Contains |
|---|---|
| **General** | Cooldown, waits/delays, image timeout & confidence, proxy slow threshold, loop forever, window size, output folder, live feed |
| **myBCA** | Login/statement URLs and waits, logout coordinates |
| **KlikBCA** | Login URL, page/menu/statement waits, tab counts, button images |
| **CIMB** | Login/statement URLs, waits, reference images |
| **Permata** | Login/statement URLs, captcha settings, OCR engine, waits, reference images |
| **Backoffice** | Enable upload, login/parse URLs, username, password, headless |

> Some technical keys (ports, robot token, Python path, Chrome path, output folder
> internals) are intentionally not shown here.

---

## 9. Users (admin only)

Manage who can sign in and their role.

### 9.1 Add a user

Enter **Username**, **Password**, pick a **Role** (`operator` or `admin`), click
**Add**. New users default to **operator**.

### 9.2 Manage users

| Column / button | What it does |
|---|---|
| Role dropdown + **Save role** | Change the user's role |
| **Reset password** | Set a new password (a prompt appears) |
| **Delete** | Remove the user |

Your own row is marked **(you)**.

**Safety rules built in:**
- You cannot delete your **own** account.
- The **last remaining admin** cannot be deleted or demoted.
- After you change your own role or password, it takes effect on your next request.

> Change the default `admin` / `123456` password here as your first action.

---

## 10. Common tasks (quick recipes)

**Start scraping a robot**
Dashboard → **Select** the robot → choose Proxy/Account (optional) → **Start**.

**Stop a robot**
Dashboard → **Select** → **Stop** (this also closes the robot's Chrome).

**Scrape one specific account next**
On the Dashboard accounts table (or the Accounts page) → **Jump Next** for that row.

**Pause an account without deleting it**
**Ban** it. It stays listed but is skipped. Use **Unban** to resume.

**Delete an account**
**Remove** it (from the Dashboard or Accounts page).

**See what was scraped**
**View** on the account row, or open `output\<label>.txt` on the robot computer.

**Change the timing/wait values**
Settings (admin) → **General** → change → **Save changes**.

**Use a proxy for a run**
Proxies page → add it, then pick it in the Dashboard's **Proxy** dropdown.

**Add a new robot**
Dashboard → **Add robot** (admin), using the robot's host, port and matching token.

**Add or remove a user**
Users page (admin).

---

## 11. How scraping behaves

- Each account opens a **fresh, temporary Chrome profile**, so there is no leftover
  session between accounts.
- A robot **loops forever** until you press **Stop**.
- **Cooldown:** an account is scraped at most once every `account_cooldown_seconds`
  (default **180s = 3 minutes**). Between accounts there is a short wait
  (`between_accounts_wait`, default 5s).
- **Ban vs Remove:** Ban keeps the account but skips it (its `enabled` flag is `no`);
  Remove deletes it entirely.
- **Saving:** the statement is written to `output\<label>.txt` only after the
  backoffice accepts it — or when the backoffice is disabled, or the statement is
  unchanged (the file is then just refreshed).
- **Unchanged statements** are not re-uploaded.
- **Not captured:** if a login page check fails, the logout button is not found, or a
  backoffice upload fails, nothing is saved and the account is passed over for now
  (its cooldown is cleared so it retries later). A debug screenshot may be left in
  `output\debug\`.
- A permanent log is written to `output\scraper.log` on the robot.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Robot **offline** | The robot's `python api.py` is not running, or Host/Port is wrong, or the **token** does not match `robot_token`. |
| Status **auth failed** | Wrong bank username/password for that account. Fix it on the Accounts page. |
| **Start** does nothing | The robot is offline; or a scraper is already running. Check **Running**/PID. |
| Account never scraped | It is **banned**, or within its **cooldown**. Unban it or wait. |
| Duplicate-label warning | The same Label exists on two robots. Remove or rename one. |
| Statement file not created | Statement was unchanged, or the backoffice upload failed. Check `output\scraper.log`. |
| Settings won't load | The robot is offline — settings are read from the robot itself. |
| Login fails after changes | Your account role/password changed; sign in again. |
| Robot keeps stopping | The computer locked (screen saver / RDP sign-out). The machine must stay unlocked — see the Installation Manual §6 (unattended cloud VM setup). |

---

## 13. Safety notes

- **Never lock the screen or sign out** while scraping. The robot controls the real
  mouse and keyboard; if the desktop is locked, scraping fails.
- On a cloud VM, always **disconnect** the RDP window, never **Sign out**.
- Keep `robot_token` secret and identical on both sides (robot `config.json` and the
  panel's robot entry).
- Change the default admin password before putting the panel on any shared network.
- Only **admins** can change settings and users — give operator accounts to staff who
  only need to run robots.
