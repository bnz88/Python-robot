# Agent Instructions

## Standing rule: always report the VM deploy steps after a push

Whenever you push commits to `origin` (or the user asks you to push), you MUST
end the response with a short **"Deploy to VM"** section containing the exact
commands the user has to run on their other VM. Tailor it to what was actually
pushed:

- Always include `git pull origin main` in the VM's repo folder.
- If `requirements.txt` or `control_panel/requirements.txt` changed, include
  the dependency reinstall commands.
- If anything under `install/` or `deploy/` changed, say whether the installer
  or `deploy\windows-unattended.ps1` has to be re-run.
- If a config key/schema changed, say whether `config.json`,
  `accounts.json` or `control_panel/config.json` must be updated.
- Always say to stop the scraper from the panel **before** updating, so
  `main.py` is not running old code.
- Always include the restart step for the panel and robot.

### Standard update block (Windows VM, repo at `C:\BCA_OS_ROBOTS`)

```powershell
cd C:\BCA_OS_ROBOTS
git pull origin main

# Only when requirements changed:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r control_panel\requirements.txt

# Restart the panel + robot (unattended install: scheduled tasks)
Stop-ScheduledTask -TaskName BCA-Robot -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName BCA-ControlPanel -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-ScheduledTask -TaskName BCA-Robot
Start-ScheduledTask -TaskName BCA-ControlPanel
```

If the VM uses the desktop launchers instead of the scheduled tasks: close the
`run_robot` and `run_panel` console windows, then double-click
`run_robot.cmd` and `run_panel.cmd`.

Do not repeat the whole installation manual; only the deltas needed for the
pushed commits.

## Other notes

- Treat `output/`, `config.json`, `accounts.json` and `.venv/` as machine-local
  runtime data; never overwrite them during an update.
- The panel Stop button now uses a cooperative stop flag and only hard-kills
  as a fallback (see `utils/stop.py`).
