# Banking Robot — Installation Manual

This manual explains, step by step, how to install and start the **Control Panel**
and the **Robot** on a Windows computer. No programming knowledge is needed — just
follow the steps in order.

> If you only want to **use** an already-installed system, read the
> [Operator & Admin Guide](OPERATOR_ADMIN_GUIDE.md) instead.

---

## 1. What you are installing

There are two programs. They normally run on the **same computer**, but they can
also run on two computers on the same network.

| Program | What it does | Start by |
|---|---|---|
| **Robot** (`api.py`) | The worker. Logs into the banks and scrapes statements. Also receives Start/Stop commands from the panel. | double-click **`run_robot.cmd`** |
| **Control Panel** (`app.py`) | The web page you open in a browser to manage robots, accounts, users and settings. | double-click **`run_panel.cmd`** |

The robot, in turn, launches the **scraper** (`main.py`) only when you press **Start**
in the panel. The scraper drives a real Chrome window.

The two launchers (`run_robot.cmd`, `run_panel.cmd`) are created for you by the
installer. A single computer can host **one panel** and **many robots**.

---

## 2. Quick install (one click)

The easiest way to install either part is to **double-click its installer**:

| Part | Double-click this file |
|---|---|
| Robot | `install\install_robot.cmd` |
| Control Panel | `install\install_panel.cmd` |

Each installer runs by itself and:

1. finds Python (and offers to install it automatically if missing);
2. creates an isolated environment in the project's `.venv` folder, so nothing
   clashes with other programs on the computer;
3. installs the correct packages;
4. creates a launcher — **`run_robot.cmd`** or **`run_panel.cmd`** — that you
   double-click to start that part.

No typing is needed. If you prefer to install by hand, or the installer reports a
problem, follow the manual steps in **§4** below — they do the same thing.

> The **panel** installer also creates the panel database and the admin account.
> Pass a password to set it during install, for example (from an Administrator
> PowerShell):
>
> ```powershell
> .\install\install_panel.cmd -PanelAdminPassword "your-new-password"
> ```

> For an always-on cloud VM, add **`-Unattended`** when running the installer from
> an **Administrator** PowerShell (see §6).

---

## 3. Before you start — checklist

- [ ] A **Windows** computer (Windows 10, 11 or Windows Server).
- [ ] **Python 3.8 or newer** installed (the installer can do this for you).
- [ ] **Google Chrome** installed.
- [ ] Internet access.
- [ ] This project folder (for example `C:\BCA_OS_ROBOTS`).
- [ ] For **Permata** accounts only: the **Tesseract OCR** program (see Step 6).
- [ ] A display that stays on. The scraper controls the real mouse and keyboard, so
      the computer **must not be locked** while it runs.

---

## 4. Manual install (one computer, step by step)

> Most people can skip this section and use the **one-click installer** in §2.
> These steps do the same thing by hand — use them if you prefer, or if the
> installer reports a problem.

### Step 1 — Install Python

1. Download Python from <https://www.python.org/downloads/windows/>.
2. During setup, **tick "Add python.exe to PATH"**, then click Install.
3. To check it worked, open **PowerShell** and type:

   ```powershell
   python --version
   ```

   You should see a version number (for example `Python 3.12.4`).

   > If Windows opens the Microsoft Store instead, Python is not installed
   > correctly. Install the real version from python.org and try again.

### Step 2 — Put the project folder on the computer

Copy the project folder somewhere simple, for example `C:\BCA_OS_ROBOTS`.

### Step 3 — Open PowerShell in the project folder

1. Open the folder in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**.
   (A PowerShell window opens already "inside" the folder.)

### Step 4 — Create the environment and install the robot's dependencies

To keep everything isolated, install into a `.venv` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This installs the robot's tools (image matching, clipboard, OCR, etc.). Wait for
it to finish.

### Step 5 — Install the panel's dependencies

Only needed on a computer that runs the Control Panel:

```powershell
.\.venv\Scripts\python.exe -m pip install -r control_panel\requirements.txt
```

> After this, use `.\.venv\Scripts\python.exe ...` to run anything in the project.
> (The one-click installer creates the `run_robot.cmd` / `run_panel.cmd` shortcuts
> that do this for you.)

### Step 6 — (Permata only) Install the Tesseract OCR program

Skip this if you do not use Permata accounts.

1. Install the Windows version of Tesseract (for example from the UB Mannheim
   installer) at `C:\Program Files\Tesseract-OCR\`.
2. The robot already expects it at that path. If you installed it elsewhere, set
   `permata_tesseract_cmd` in `config.json` (Step 9) to the full path of
   `tesseract.exe`.

### Step 7 — (For the backoffice upload) Download the browser engine

Only needed if statements must be uploaded to the Sistem88 backoffice
(`"enabled": true` under `backoffice` in `config.json`). The Playwright package is
already installed by Step 4; only the browser needs downloading:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### Step 8 — Capture the reference images (first time only)

The robot finds buttons by matching small saved pictures. Capture them once:

```powershell
.\.venv\Scripts\python.exe main.py --capture
```

For each bank the script opens the login page and pauses. Save the small pictures
listed in `README.md` (for example `assets\klikbca\login_button.png`). Crop **tightly**
around each button. You can skip banks you do not use.

### Step 9 — Check `config.json`

`config.json` and `control_panel\config.json` are not stored in the repository
(they hold live credentials). The installers create them from
`config.example.json` / `control_panel\config.example.json`; if you install by
hand, copy both files yourself and replace every `CHANGE_ME` value.

Open `config.json` in Notepad and confirm these values (most are already correct):

| Setting | Meaning | Typical value |
|---|---|---|
| `chrome_exe` | Where Chrome is installed | `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| `window_width` / `window_height` | Fixed browser window size when `chrome_maximized` is disabled; your screen must be at least this big | `1280` / `900` |
| `chrome_maximized` | Open Chrome maximized (full screen) on every scrape | `true` |
| `api_host` | Address the robot listens on | `0.0.0.0` |
| `api_port` | Port the robot listens on | `8000` |
| `robot_token` | A secret password between the panel and the robot | any long random text |
| `python_exe` | Which Python starts the scraper | leave `null` normally |

> **Security:** change `robot_token` to a long random value and use the **same**
> value when you add the robot in the panel (Step 13).

### Step 10 — Start the Robot

Double-click **`run_robot.cmd`** in the project folder. Or, in a PowerShell window:

```powershell
.\.venv\Scripts\python.exe api.py
```

You should see:

```
robot API listening on http://0.0.0.0:8000/
```

**Leave this window open.** It is the robot's server.

### Step 11 — Start the Control Panel

Double-click **`run_panel.cmd`**. Or, in a **second** PowerShell window:

```powershell
.\.venv\Scripts\python.exe control_panel\app.py
```

You should see:

```
control panel listening on http://0.0.0.0:5000
```

**Leave this window open too.**

### Step 12 — Open the panel in your browser

Go to:

```
http://127.0.0.1:5000
```

Log in with the default account:

- Username: `admin`
- Password: `123456`

> **Important:** change this password right away (see the Operator & Admin Guide →
> *Users page*).

### Step 13 — Add the robot to the panel

1. On the **Dashboard**, open **Add robot**.
2. Fill in:

   | Field | What to enter |
   |---|---|
   | Name | A label, e.g. `robot1` |
   | Host | `127.0.0.1` (use the robot's IP if it is another computer) |
   | Port | `8000` |
   | Token | The same value as `robot_token` in `config.json` |
   | Proxy | optional — leave as *none* if you have no proxy |

3. Click **Add**. The robot appears in the list and should show **online**.

### Step 14 — Add accounts

1. Open the **Accounts** page.
2. Under **Add bank account**, choose the robot, the bank, and fill in the account
   details (Label, Unique ID, Shortname, Username, Password).
3. Click **Add**.

> The **Label** must be unique across all robots — it also becomes the output file
> name (`output\<label>.txt`).

### Step 15 — Start scraping

1. Go back to the **Dashboard**.
2. Click **Select** next to the robot, choose which accounts to run (or leave
   *all*), then click **Start**.
3. A Chrome window opens and begins working. You can watch progress on the
   **Live Logs** page and the **Live** page (screen feed).

**Done.** To stop, click **Stop** — this closes the scraper and its Chrome window.

---

## 5. Two computers (panel and robot separate)

The simplest way: run **`install\install_robot.cmd`** on the robot computer and
**`install\install_panel.cmd`** on the panel computer. (By hand, the robot needs
Steps 1–4 and the panel needs Steps 1–5.)

On the **robot** computer: make sure `api_host` is `0.0.0.0` and start
`run_robot.cmd`. On the **panel** computer: start `run_panel.cmd`, then add the robot
using the robot computer's **IP address** as the Host (instead of `127.0.0.1`).

Make sure Windows Firewall on each computer allows the other:
- Panel port **5000** reachable from the operator's computer.
- Robot port **8000** reachable from the panel computer.

---

## 6. Running it on a cloud Windows VM, unattended

If the panel and robot must keep running on a cloud Windows VM even after you close
the Remote Desktop window, install them first (§2), then run the unattended setup
**once** from an **Administrator** PowerShell on that VM:

```powershell
.\deploy\windows-unattended.ps1 -AutoLogonUser <windows-user> -PanelAdminPassword "<new-panel-password>" -PanelAllow <operator-vm-ip>
```

It will:

- stop the screen from locking (so the mouse/keyboard automation keeps working);
- keep a **disconnected** RDP session alive;
- open the firewall only to your private network;
- start the panel and the robot automatically at logon (but **not** scraping — you
  still press Start yourself);
- optionally set up auto-login so the VM boots without you.

The installers can do this step for you: run the installer from an Administrator
PowerShell with **`-Unattended`**.

After it finishes, **reboot the VM** to confirm both servers come up on their own.

> Always **disconnect** the RDP window (click the **X**). Never choose **Sign out** —
> that closes everything.

To undo the setup: `.\deploy\windows-unattended.ps1 -Remove`

---

## 7. Where files live

| File / folder | What it is |
|---|---|
| `config.json` | Robot settings (Chrome path, timing, token, ports) |
| `accounts.json` | The robot's account list (edited by the panel's Accounts page) |
| `output\<label>.txt` | The scraped statement for each account |
| `output\scraper.log` | Robot log file |
| `assets\` | Saved reference images used to find buttons |
| `control_panel\config.json` | Panel settings (host, port, admin login) |
| `control_panel\panel.db` | Panel database (robots, users, proxies) |
| `.venv\` | Isolated Python environment (created by the installer) |
| `install\` | The one-click installers (`install_robot.cmd`, `install_panel.cmd`) |
| `run_robot.cmd` / `run_panel.cmd` | Double-click launchers for the robot / panel |
| `deploy\windows-unattended.ps1` | One-time cloud/VM setup script |

---

## 8. Troubleshooting

| Problem | What to do |
|---|---|
| `python` opens the Microsoft Store | Install Python from python.org with "Add to PATH" ticked, then run the one-click installer again. |
| The installer says Python is missing | Let it install Python with winget, or install Python 3 manually and re-run the installer. |
| `robot API listening...` never appears | Another program uses port 8000, or the packages are missing. Re-run `install\install_robot.cmd` and check the message. |
| Robot shows **offline** in the panel | `run_robot.cmd` is not running, or Host/Port is wrong, or the **token** does not match `robot_token`. |
| **auth failed** status | The bank rejected the username/password. Fix the account in the Accounts page. |
| Nothing is scraped | The robot is online but you have not pressed **Start**, accounts are banned, or all are within the cooldown (default 3 minutes). |
| Buttons not found / wrong field typed | Re-capture the reference images (Step 8) or adjust `tabs_to_username` in `config.json`. |
| Image is found but the click does nothing (or lands elsewhere) | Windows display scaling is not 100 %, or another window is in front of Chrome. Set scaling to 100 % on the robot desktop and keep the Chrome window maximized and in front; the log prints `display scaling detected` when a scale correction is applied. |
| The run stops when you lock the screen | The computer must stay unlocked. On a cloud VM use §6. |
| Statement file not created | The statement was unchanged, or the backoffice upload failed. See `output\scraper.log`. |

---

## 9. Stopping everything

1. In the panel, click **Stop** for each running robot.
2. Close the **`run_robot`** and **`run_panel`** windows to stop the servers
   (or press **Ctrl+C** in the window that is running them).
