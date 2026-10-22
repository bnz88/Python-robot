"""HTTP API for the BCA scraper: serve statements and control the runner.

Read routes:
    GET /<bank>/<label>      e.g. GET /mybca/SYAHRUDIN992
        -> contents of output/<label>.txt as text/plain
        -> 404 with JSON null when the label has no output yet.

Control routes (GET or POST):
    GET|POST /control/start[?account=mybca|klikbca]  -> start `python main.py`
    GET|POST /control/stop                            -> stop the running scraper
    GET      /control/status                          -> {"running": bool, "pid": int|null}

Run:
    python api.py
Host/port come from config.json (``api_host``, ``api_port``).
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from utils.output import log, sanitize_label

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
KNOWN_BANKS = ("klikbca", "mybca", "cimb", "permata")

# Settings exposed to the panel, grouped into tabs. Each field is
# {"key", "label", "type", "default", ...}. Nested keys use dots (e.g.
# "backoffice.enabled"). Server/infra and secret keys (robot_token,
# api_host/port, python_exe, scraper_script, log_file, chrome_exe,
# user_data_dir, assets_dir) are intentionally excluded.
CONFIG_SCHEMA = [
    {
        "id": "general",
        "title": "General",
        "fields": [
            {"key": "account_cooldown_seconds", "label": "Per-account cooldown (s)", "type": "int", "default": 180},
            {"key": "between_accounts_wait", "label": "Wait between accounts (s)", "type": "float", "default": 5.0},
            {"key": "delay_short", "label": "Short delay (s)", "type": "float", "default": 0.5},
            {"key": "delay_long", "label": "Long delay (s)", "type": "float", "default": 2.5},
            {"key": "page_load_wait", "label": "Page load wait (s)", "type": "float", "default": 4.0},
            {"key": "image_timeout", "label": "Image click timeout (s)", "type": "int", "default": 15},
            {"key": "image_confidence", "label": "Image match confidence", "type": "float", "default": 0.85, "min": 0, "max": 1},
            {"key": "stop_timeout", "label": "Stop/kill timeout (s)", "type": "int", "default": 20},
            {"key": "loop_forever", "label": "Loop forever", "type": "bool", "default": True},
            {"key": "window_width", "label": "Window width (px)", "type": "int", "default": 1280},
            {"key": "window_height", "label": "Window height (px)", "type": "int", "default": 900},
            {"key": "chrome_maximized", "label": "Open Chrome maximized", "type": "bool", "default": True, "help": "Maximize Chrome on every scrape. Window width/height are used only when this is off."},
            {"key": "window_title_hint", "label": "Window title hint", "type": "text", "default": "Google Chrome"},
            {"key": "output_dir", "label": "Output directory", "type": "text", "default": "output"},
            {"key": "live_capture", "label": "Live screen feed", "type": "bool", "default": True, "help": "Capture the desktop to output/live/frame.jpg while the scraper runs."},
            {"key": "live_interval", "label": "Live feed interval (s)", "type": "float", "default": 1.0, "min": 0.5, "help": "Seconds between desktop captures."},
        ],
    },
    {
        "id": "mybca",
        "title": "myBCA",
        "fields": [
            {"key": "mybca_login_url", "label": "Login URL", "type": "text", "default": ""},
            {"key": "mybca_statement_url", "label": "Statement URL", "type": "text", "default": ""},
            {"key": "mybca_login_wait", "label": "Login wait (s)", "type": "float", "default": 7.0},
            {"key": "mybca_dashboard_wait", "label": "Dashboard wait (s)", "type": "float", "default": 7.0},
            {"key": "mybca_statement_wait", "label": "Statement wait (s)", "type": "float", "default": 10.0},
            {"key": "mybca_logout_wait", "label": "Logout wait (s)", "type": "float", "default": 2.0},
            {"key": "mybca_logout_process_wait", "label": "Logout process wait (s)", "type": "float", "default": 3.0},
            {"key": "mybca_logout_x", "label": "Logout button X", "type": "int", "default": None, "nullable": True, "help": "Leave empty to use the default."},
            {"key": "mybca_logout_y", "label": "Logout button Y", "type": "int", "default": None, "nullable": True, "help": "Leave empty to use the default."},
            {"key": "mybca_omitted_rows", "label": "Omitted rows (x N)", "type": "int", "default": None, "nullable": True, "placeholder": "auto", "help": "Empty or 0 = auto-detect; a positive number forces the count."},
        ],
    },
    {
        "id": "klikbca",
        "title": "KlikBCA",
        "fields": [
            {"key": "klikbca_login_url", "label": "Login URL", "type": "text", "default": ""},
            {"key": "klikbca_landing_page", "label": "Landing page image", "type": "text", "default": "landingpage.PNG", "help": "Image inside assets/klikbca that must appear before login starts."},
            {"key": "klikbca_page_timeout", "label": "Page check timeout (s)", "type": "int", "default": 20, "help": "How long to wait for the landing/dashboard image before the account is skipped (cooldown cleared, next account continues)."},
            {"key": "klikbca_login_wait", "label": "Login wait (s)", "type": "float", "default": 5.0},
            {"key": "klikbca_dashboard_wait", "label": "Dashboard wait (s)", "type": "float", "default": 7.0},
            {"key": "klikbca_menu_tabs", "label": "Menu tabs to press", "type": "int", "default": 10},
            {"key": "klikbca_menu_wait", "label": "Menu wait (s)", "type": "float", "default": 2.0},
            {"key": "klikbca_stmt_tabs", "label": "Statement tabs to press", "type": "int", "default": 3},
            {"key": "klikbca_stmt_wait", "label": "Statement tab wait (s)", "type": "float", "default": 3.0},
            {"key": "klikbca_statement_wait", "label": "Statement load wait (s)", "type": "float", "default": 10.0},
            {"key": "klikbca_stmt_fallback_tabs", "label": "Statement fallback tabs", "type": "int", "default": 14},
            {"key": "klikbca_statement_buttons", "label": "Statement button images", "type": "csv", "default": [], "help": "Comma-separated image names inside assets/klikbca (bare names, not full paths)."},
            {"key": "klikbca_stmt_button_timeout", "label": "Statement button search (s)", "type": "float", "default": 5.0, "help": "How long to look for each statement button image before falling back to tabs."},
            {"key": "klikbca_logout_button", "label": "Logout button image", "type": "text", "default": "logout_button.PNG"},
            {"key": "klikbca_logout_wait", "label": "Logout wait (s)", "type": "float", "default": 3.0},
            {"key": "klikbca_omitted_rows", "label": "Omitted rows (x N)", "type": "int", "default": None, "nullable": True, "placeholder": "auto", "help": "Empty or 0 = auto-detect; a positive number forces the count."},
        ],
    },
    {
        "id": "cimb",
        "title": "CIMB",
        "fields": [
            {"key": "cimb_login_url", "label": "Login URL", "type": "text", "default": "https://www.cimbocto.co.id/login"},
            {"key": "cimb_statement_url", "label": "Statement URL", "type": "text", "default": "https://www.cimbocto.co.id/myaccount/casa/1"},
            {"key": "cimb_user_id_image", "label": "User ID image", "type": "text", "default": "user_id.JPG"},
            {"key": "cimb_logout_button", "label": "Logout button image", "type": "text", "default": "cimb_logout_btn.JPG"},
            {"key": "cimb_page_timeout", "label": "Page timeout (s)", "type": "float", "default": 20.0},
            {"key": "cimb_login_wait", "label": "Login wait (s)", "type": "float", "default": 5.0},
            {"key": "cimb_submit_wait", "label": "Submit wait (s)", "type": "float", "default": 1.0},
            {"key": "cimb_logged_in_wait", "label": "Logged-in wait (s)", "type": "float", "default": 5.0},
            {"key": "cimb_statement_wait", "label": "Statement wait (s)", "type": "float", "default": 8.0},
            {"key": "cimb_logout_wait", "label": "Logout wait (s)", "type": "float", "default": 5.0},
            {"key": "cimb_omitted_rows", "label": "Omitted rows (x N)", "type": "int", "default": None, "nullable": True, "placeholder": "none", "help": "Manual only (no auto-detect): empty or 0 = no omit; a positive number forces the count."},
        ],
    },
    {
        "id": "permata",
        "title": "Permata",
        "fields": [
            {"key": "permata_login_url", "label": "Login URL", "type": "text", "default": "https://www.permatanet.com/pnet/"},
            {"key": "permata_statement_url", "label": "Statement URL", "type": "text", "default": "https://www.permatanet.com/pnet/saving-detail/IDR#mutation"},
            {"key": "permata_close_button", "label": "Landing close button image", "type": "text", "default": "close_button.JPG", "help": "Image inside assets/permata for the landing-page modal close button."},
            {"key": "permata_close_wait", "label": "Close button wait (s)", "type": "float", "default": 3.0, "help": "Seconds to wait after the close button is found before clicking it."},
            {"key": "permata_user_id_images", "label": "Username field images", "type": "csv", "default": ["user_id1.JPG", "user_id2.JPG"], "help": "Comma-separated image names inside assets/permata; the first match is clicked to focus the username field (e.g. Indonesian/English labels)."},
            {"key": "permata_user_icon", "label": "User icon image", "type": "text", "default": "user_icon.JPG", "help": "Login gate (also the logout menu opener). Its middle letters vary; matched at the icon confidence."},
            {"key": "permata_icon_confidence", "label": "User icon confidence", "type": "float", "default": 0.7, "min": 0, "max": 1, "help": "Match threshold for the user icon (lower because its middle letters change)."},
            {"key": "permata_login_wait", "label": "Login wait (s)", "type": "float", "default": 5.0},
            {"key": "permata_dashboard_wait", "label": "Post-submit wait (s)", "type": "float", "default": 7.0, "help": "Seconds to wait for the login result on the final captcha attempt (also used when there is no retry)."},
            {"key": "permata_captcha_retry_wait", "label": "Captcha retry wait (s)", "type": "float", "default": 3.0, "help": "Shorter wait for the login result after a failed captcha attempt, so the next attempt follows sooner."},
            {"key": "permata_after_login_wait", "label": "After-login wait (s)", "type": "float", "default": 3.0},
            {"key": "permata_ind_flag", "label": "Statement flag image", "type": "text", "default": "ind_flag.JPG", "help": "Image located on the statement page and clicked to load the mutations."},
            {"key": "permata_ind_flag_wait", "label": "Flag click wait (s)", "type": "float", "default": 3.0},
            {"key": "permata_scroll_step_px", "label": "Statement scroll step (px)", "type": "int", "default": 100, "min": 20, "help": "Scroll down this many pixels at a time while looking for the statement flag."},
            {"key": "permata_scroll_max_steps", "label": "Statement scroll steps", "type": "int", "default": 20, "min": 0, "help": "Maximum scroll steps before giving up (0 disables scrolling)."},
            {"key": "permata_statement_wait", "label": "Statement load wait (s)", "type": "float", "default": 8.0},
            {"key": "permata_capture_wait", "label": "Post-capture wait (s)", "type": "float", "default": 3.0},
            {"key": "permata_logout_open_wait", "label": "Logout menu wait (s)", "type": "float", "default": 2.0},
            {"key": "permata_logout_process_wait", "label": "Logout process wait (s)", "type": "float", "default": 3.0},
            {"key": "permata_captcha_attempts", "label": "Captcha attempts", "type": "int", "default": 2, "help": "Initial captcha attempt + retries. After the last failure the account is aborted (cooldown cleared, next account continues)."},
            {"key": "permata_captcha_image", "label": "Captcha reference image", "type": "text", "default": "captcha.JPG", "help": "Image inside assets/permata used to locate the captcha on screen before OCR."},
            {"key": "permata_captcha_confidence", "label": "Captcha locate confidence", "type": "float", "default": 0.5, "min": 0, "max": 1, "help": "Match threshold for the captcha reference image (letters change, so lower than image_confidence)."},
            {"key": "permata_captcha_padding", "label": "Captcha crop padding (px)", "type": "int", "default": 0, "help": "Pixels added around the located captcha before OCR (0 = tight crop; ddddocr prefers a tight crop)."},
            {"key": "permata_captcha_blur", "label": "Captcha locate blur (px)", "type": "int", "default": 15, "help": "Blur (odd) applied when locating the captcha so it matches on the background pattern, not the changing letters."},
            {"key": "permata_captcha_candidates", "label": "Captcha candidates", "type": "int", "default": 10, "help": "Max candidate locations tried (OCR-validated) before giving up."},
            {"key": "permata_captcha_x", "label": "Captcha region X", "type": "int", "default": None, "nullable": True, "help": "Screen x of the captcha image; fill after capture."},
            {"key": "permata_captcha_y", "label": "Captcha region Y", "type": "int", "default": None, "nullable": True, "help": "Screen y of the captcha image; fill after capture."},
            {"key": "permata_captcha_w", "label": "Captcha region W", "type": "int", "default": None, "nullable": True, "help": "Width of the captcha image region."},
            {"key": "permata_captcha_h", "label": "Captcha region H", "type": "int", "default": None, "nullable": True, "help": "Height of the captcha image region."},
            {"key": "permata_captcha_length", "label": "Captcha length", "type": "int", "default": 4},
            {"key": "permata_captcha_charset", "label": "Captcha charset", "type": "text", "default": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", "help": "Allowed captcha characters, case-sensitive (mixed-case captchas)."},
            {"key": "permata_ocr_engine", "label": "OCR engine", "type": "text", "default": "auto", "help": "'auto' (default: prefer Tesseract's case when it agrees with ddddocr's letters), or force 'ddddocr'/'tesseract'."},
            {"key": "permata_tesseract_cmd", "label": "Tesseract exe path", "type": "text", "default": "", "help": "Path to tesseract.exe on this robot (optional if it is on PATH)."},
            {"key": "permata_case_mode", "label": "Case resolution mode", "type": "text", "default": "auto", "help": "'auto' (font then tesseract, default), 'font' (font template only), 'tesseract' (Tesseract case only) or 'baseline' (skip case resolution)."},
            {"key": "permata_font_file", "label": "Captcha font file", "type": "text", "default": "assets/permata/font.json", "help": "font.json produced by tools/permata_font_id.py; used to resolve each glyph's case without training."},
            {"key": "permata_case_min_score", "label": "Font case min margin", "type": "float", "default": 0.05, "min": 0, "max": 1, "help": "Minimum mean upper-vs-lower margin to accept the font template's case; below it the resolver falls back to Tesseract/baseline."},
            {"key": "permata_capture_samples", "label": "Capture captcha samples", "type": "bool", "default": False, "help": "Save each located captcha crop to dataset/permata/images; a successful login records its label automatically."},
            {"key": "permata_logout_button", "label": "Logout button image", "type": "text", "default": "logout_btn_permata.JPG"},
            {"key": "permata_omitted_rows", "label": "Omitted rows (x N)", "type": "int", "default": None, "nullable": True, "placeholder": "none", "help": "Manual only (no auto-detect): empty or 0 = no omit; a positive number forces the count."},
        ],
    },
    {
        "id": "backoffice",
        "title": "Backoffice",
        "fields": [
            {"key": "backoffice.enabled", "label": "Enabled", "type": "bool", "default": False},
            {"key": "backoffice.headless", "label": "Headless browser", "type": "bool", "default": True},
            {"key": "backoffice.skip_save", "label": "Skip save (dry run)", "type": "bool", "default": False},
            {"key": "backoffice.dry_run_keep_open", "label": "Dry run: keep browser open", "type": "bool", "default": True, "help": "Dry run only: keep the browser open after the flow (on success and error) until the window is closed. Turn off to close it and continue to the next account."},
            {"key": "backoffice.username", "label": "Username", "type": "text", "default": ""},
            {"key": "backoffice.password", "label": "Password", "type": "password", "default": ""},
            {"key": "backoffice.login_url", "label": "Login URL", "type": "text", "default": ""},
            {"key": "backoffice.parse_url", "label": "Parse page URL", "type": "text", "default": ""},
            {"key": "backoffice.parse_api_url", "label": "Parse API URL", "type": "text", "default": ""},
            {"key": "backoffice.save_api_url", "label": "Save API URL", "type": "text", "default": ""},
            {"key": "backoffice.success_selector", "label": "Success selector", "type": "text", "default": ""},
        ],
    },
]


def _cfg_get(config, key, default=None):
    node = config
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _cfg_set(config, key, value):
    parts = key.split(".")
    node = config
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


CONFIG_FIELDS = {
    field["key"]: field for tab in CONFIG_SCHEMA for field in tab["fields"]
}


def _coerce_field(field, raw):
    """Coerce a submitted value to the field's declared type."""
    key = field["key"]
    ftype = field["type"]
    if ftype == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if ftype in ("int", "float"):
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if field.get("nullable"):
                return None
            raise ValueError("{}: must be a number".format(key))
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError("{}: must be a number".format(key))
        low, high = field.get("min"), field.get("max")
        if (low is not None and num < low) or (high is not None and num > high):
            raise ValueError(
                "{}: must be between {} and {}".format(key, low, high)
            )
        return int(num) if ftype == "int" else num
    if ftype == "csv":
        items = raw if isinstance(raw, list) else str(raw).split(",")
        return [str(item).strip() for item in items if str(item).strip()]
    return "" if raw is None else str(raw)


def _normalize_omitted_rows(raw):
    """Return a positive int, or None when unset/zero/empty (means 'auto')."""
    if raw is None or raw == "" or raw is False:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit("config.json not found at {}".format(CONFIG_PATH))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def output_dir_from(config):
    output_dir = config.get("output_dir", "output")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(BASE_DIR, output_dir)
    return output_dir


def log_file_from(config):
    log_file = config.get("log_file")
    if not log_file:
        return None
    if not os.path.isabs(log_file):
        log_file = os.path.join(BASE_DIR, log_file)
    return log_file


def status_file_from(config):
    """Path of the scraper's live status file (current/next account)."""
    return os.path.join(output_dir_from(config), "status.json")


def read_status(config):
    """Read the scraper's status file; returns {} when absent/unreadable."""
    path = status_file_from(config)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def kill_tree(pid):
    """Force-kill a process and its children (Windows uses taskkill /T)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


class ProcessManager:
    """Start/stop `python main.py` as a single managed child process."""

    def __init__(self, base_dir, config):
        self.base_dir = base_dir
        self.config = config
        self.lock = threading.Lock()
        self.process = None

    def _script_path(self):
        script = self.config.get("scraper_script", "main.py")
        if os.path.isabs(script):
            return script
        return os.path.join(self.base_dir, script)

    def _python_exe(self):
        return self.config.get("python_exe") or sys.executable

    def status(self):
        with self.lock:
            if self.process is None:
                base = {"running": False, "pid": None, "returncode": None}
            else:
                code = self.process.poll()
                base = {
                    "running": code is None,
                    "pid": self.process.pid,
                    "returncode": code,
                }
        info = read_status(self.config)
        base["current_account"] = info.get("current")
        base["next_account"] = info.get("next")
        base["status_updated"] = info.get("updated")
        return base

    def start(self, extra_args=None):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return {
                    "started": False,
                    "running": True,
                    "pid": self.process.pid,
                    "message": "already running",
                }

            cmd = [self._python_exe(), self._script_path()]
            if extra_args:
                cmd.extend(extra_args)

            # Truncate the log file so /control/log shows only the current run.
            log_file = log_file_from(self.config)
            if log_file:
                try:
                    directory = os.path.dirname(log_file)
                    if directory:
                        os.makedirs(directory, exist_ok=True)
                    with open(log_file, "w", encoding="utf-8", errors="replace"):
                        pass
                except OSError as exc:
                    log("[api] could not truncate log file {}: {}".format(log_file, exc))

            # Drop any stale current/next status from a previous run.
            status_path = status_file_from(self.config)
            try:
                if os.path.isfile(status_path):
                    os.remove(status_path)
            except OSError:
                pass

            # Open a visible console window on the desktop so the scraper's
            # verbose logs (from utils.output.log) are shown as it runs. The
            # own process group lets /control/stop deliver Ctrl+Break.
            creationflags = 0
            if os.name == "nt":
                creationflags = (
                    subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
                )

            try:
                self.process = subprocess.Popen(
                    cmd,
                    cwd=self.base_dir,
                    stdout=None,
                    stderr=None,
                    creationflags=creationflags,
                )
            except Exception as exc:
                return {"started": False, "running": False, "message": str(exc)}

            log("[api] started scraper pid {}: {}".format(self.process.pid, cmd))
            return {
                "started": True,
                "running": True,
                "pid": self.process.pid,
                "message": "started",
            }

    def stop(self, timeout=None):
        timeout = timeout if timeout is not None else self.config.get("stop_timeout", 20)
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.process = None
                return {"stopped": False, "running": False, "message": "not running"}
            proc = self.process

        # The scraper runs in its own console, so a console control signal
        # cannot be delivered from here. Force-kill the process tree
        # (python + any Chrome it opened); the console window closes when the
        # process attached to it exits.
        log("[api] stopping scraper pid {} (killing process tree)".format(proc.pid))
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=timeout)
        except Exception:
            pass

        with self.lock:
            self.process = None

        log("[api] scraper stopped")
        return {"stopped": True, "running": False, "message": "stopped"}


class StatementHandler(BaseHTTPRequestHandler):
    config = {}
    manager = None

    # ------------------------------------------------------------------ routing
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        if path == "health":
            self._send_json(200, {"ok": True})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        if self._handle_control(path, query):
            return
        self._serve_statement(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        if self._handle_control(path, query):
            return
        self._send_json(404, None)

    def _authorized(self):
        token = self.config.get("robot_token", "")
        if not token:
            return True
        return self.headers.get("X-Robot-Token", "") == token

    def _handle_control(self, path, query):
        if path == "control/status":
            self._send_json(200, self.manager.status())
            return True
        if path == "control/log":
            self._log_tail(query)
            return True
        if path == "live/image":
            self._serve_live()
            return True
        if path == "accounts":
            if self.command == "POST":
                self._add_account()
            else:
                self._accounts_list()
            return True
        if path.startswith("accounts/") and path.endswith("/remove"):
            label = unquote(path[len("accounts/"):-len("/remove")])
            self._remove_account(label)
            return True
        if path.startswith("accounts/") and path.endswith("/update"):
            label = unquote(path[len("accounts/"):-len("/update")])
            self._update_account(label)
            return True
        for suffix, enabled in (("ban", False), ("unban", True)):
            mark = "/" + suffix
            if path.startswith("accounts/") and path.endswith(mark):
                label = unquote(path[len("accounts/"):-len(mark)])
                self._set_enabled(label, enabled)
                return True
        if path == "control/start":
            extra = []
            account = (query.get("account") or [None])[0]
            if account in KNOWN_BANKS:
                extra = ["--account", account]
            proxy_ip = (query.get("ip") or [None])[0]
            proxy_port = (query.get("port") or [None])[0]
            if proxy_ip and proxy_port:
                try:
                    int(proxy_port)
                except (TypeError, ValueError):
                    self._send_json(
                        400,
                        {
                            "error": "port must be an integer",
                            "started": False,
                            "running": False,
                        },
                    )
                    return True
                extra += ["--proxy-ip", proxy_ip, "--proxy-port", str(int(proxy_port))]
            self._send_json(200, self.manager.start(extra))
            return True
        if path == "control/stop":
            self._send_json(200, self.manager.stop())
            return True
        if path == "next" and self.command == "POST":
            label = (query.get("label") or [None])[0]
            if not label:
                self._send_json(400, {"error": "label required"})
                return True
            if not self._label_known(label):
                self._send_json(404, {"error": "unknown account label"})
                return True
            try:
                self._set_next_override(label)
            except OSError as exc:
                self._send_json(500, {"error": "write failed: {}".format(exc)})
                return True
            log("[api] set one-time next-scrape override for {}".format(label))
            self._send_json(200, {"ok": True, "label": label})
            return True
        if path == "config":
            if self.command == "POST":
                self._config_update()
            else:
                self._config_get()
            return True
        return False

    # ------------------------------------------------------------------ statement
    def _serve_statement(self, path):
        parts = [unquote(p) for p in path.split("/") if p]
        if len(parts) != 2:
            self._not_found("expected /<bank>/<label>")
            return

        bank, label = parts[0].lower(), parts[1]
        if bank not in KNOWN_BANKS:
            self._not_found("unknown bank: {}".format(bank))
            return

        path_fs = os.path.join(
            output_dir_from(self.config), "{}.txt".format(sanitize_label(label))
        )
        if not os.path.isfile(path_fs):
            self._not_found("no output for label: {}".format(label))
            return

        try:
            with open(path_fs, "rb") as f:
                body = f.read()
        except OSError as exc:
            self._not_found("read error: {}".format(exc))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ live image
    def _serve_live(self):
        """Serve the latest live screenshot written by the scraper."""
        path_fs = os.path.join(output_dir_from(self.config), "live", "frame.jpg")
        if not os.path.isfile(path_fs):
            self._not_found("no live frame yet")
            return
        try:
            with open(path_fs, "rb") as f:
                body = f.read()
        except OSError as exc:
            self._not_found("read error: {}".format(exc))
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ accounts
    def _accounts_list(self):
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        if not os.path.isfile(accounts_path):
            self._send_json(200, [])
            return
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except (OSError, ValueError) as exc:
            self._send_json(
                500, {"error": "accounts.json unreadable: {}".format(exc)}
            )
            return
        out_dir = output_dir_from(self.config)
        result = []
        for acc in accounts:
            if not isinstance(acc, dict) or not acc.get("label"):
                continue
            label = acc["label"]
            out_path = os.path.join(out_dir, "{}.txt".format(sanitize_label(label)))
            exists = os.path.isfile(out_path)
            mtime = os.path.getmtime(out_path) if exists else None
            result.append(
                {
                    "label": label,
                    "bank": acc.get("bank"),
                    "enabled": bool(acc.get("enabled", True)),
                    "unique_id": acc.get("unique_id"),
                    "bank_shortname": acc.get("bank_shortname"),
                    "omitted_rows": acc.get("omitted_rows"),
                    "output_exists": exists,
                    "last_scrape": mtime,
                }
            )
        self._send_json(200, result)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _add_account(self):
        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json(400, {"error": "expected a JSON object body"})
            return
        bank = body.get("bank")
        label = (body.get("label") or "").strip()
        username = body.get("username")
        password = body.get("password")
        if bank not in KNOWN_BANKS:
            self._send_json(400, {"error": "bank must be 'klikbca', 'mybca', 'cimb' or 'permata'"})
            return
        for key, value in (("label", label), ("username", username), ("password", password)):
            if not value:
                self._send_json(400, {"error": "missing field: {}".format(key)})
                return

        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        accounts = []
        if os.path.isfile(accounts_path):
            try:
                with open(accounts_path, "r", encoding="utf-8") as f:
                    accounts = json.load(f)
            except (OSError, ValueError) as exc:
                self._send_json(
                    500, {"error": "accounts.json unreadable: {}".format(exc)}
                )
                return
        if not isinstance(accounts, list):
            accounts = []
        if any(a.get("label") == label for a in accounts):
            self._send_json(409, {"error": "label already exists on this robot"})
            return

        entry = {
            "bank": bank,
            "username": username,
            "password": password,
            "label": label,
        }
        if "enabled" in body:
            entry["enabled"] = bool(body["enabled"])
        if body.get("unique_id") is not None:
            entry["unique_id"] = body.get("unique_id")
        if body.get("bank_shortname") is not None:
            entry["bank_shortname"] = body.get("bank_shortname")
        if "omitted_rows" in body:
            omitted = _normalize_omitted_rows(body.get("omitted_rows"))
            if omitted is not None:
                entry["omitted_rows"] = omitted
        accounts.append(entry)
        try:
            self._atomic_write_accounts(accounts)
        except OSError as exc:
            self._send_json(500, {"error": "write failed: {}".format(exc)})
            return
        log("[api] added account {!r} ({})".format(label, bank))
        self._send_json(
            200,
            {
                "label": label,
                "bank": bank,
                "enabled": entry.get("enabled", True),
                "unique_id": entry.get("unique_id"),
                "bank_shortname": entry.get("bank_shortname"),
            },
        )

    def _remove_account(self, label):
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        if not os.path.isfile(accounts_path):
            self._send_json(404, {"error": "no such label"})
            return
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except (OSError, ValueError) as exc:
            self._send_json(
                500, {"error": "accounts.json unreadable: {}".format(exc)}
            )
            return
        remaining = [a for a in accounts if a.get("label") != label]
        if len(remaining) == len(accounts):
            self._send_json(404, {"error": "no such label"})
            return
        try:
            self._atomic_write_accounts(remaining)
        except OSError as exc:
            self._send_json(500, {"error": "write failed: {}".format(exc)})
            return
        log("[api] removed account {!r}".format(label))
        self._send_json(200, {"label": label, "removed": True})

    def _set_enabled(self, label, enabled):
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        if not os.path.isfile(accounts_path):
            self._send_json(404, {"error": "no such label"})
            return
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except (OSError, ValueError) as exc:
            self._send_json(
                500, {"error": "accounts.json unreadable: {}".format(exc)}
            )
            return
        found = False
        for acc in accounts:
            if acc.get("label") == label:
                acc["enabled"] = bool(enabled)
                found = True
        if not found:
            self._send_json(404, {"error": "no such label"})
            return
        try:
            self._atomic_write_accounts(accounts)
        except OSError as exc:
            self._send_json(500, {"error": "write failed: {}".format(exc)})
            return
        log("[api] set account {!r} enabled={}".format(label, bool(enabled)))
        self._send_json(200, {"label": label, "enabled": bool(enabled)})

    def _update_account(self, label):
        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json(400, {"error": "expected a JSON object body"})
            return
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        if not os.path.isfile(accounts_path):
            self._send_json(404, {"error": "no such label"})
            return
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except (OSError, ValueError) as exc:
            self._send_json(
                500, {"error": "accounts.json unreadable: {}".format(exc)}
            )
            return
        entry = next((a for a in accounts if a.get("label") == label), None)
        if entry is None:
            self._send_json(404, {"error": "no such label"})
            return
        for key in ("bank", "username", "password", "unique_id", "bank_shortname"):
            if key in body:
                entry[key] = body[key]
        if "enabled" in body:
            entry["enabled"] = bool(body["enabled"])
        if "omitted_rows" in body:
            omitted = _normalize_omitted_rows(body.get("omitted_rows"))
            if omitted is None:
                entry.pop("omitted_rows", None)
            else:
                entry["omitted_rows"] = omitted
        try:
            self._atomic_write_accounts(accounts)
        except OSError as exc:
            self._send_json(500, {"error": "write failed: {}".format(exc)})
            return
        log("[api] updated account {!r}".format(label))
        self._send_json(
            200,
            {
                "label": label,
                "unique_id": entry.get("unique_id"),
                "bank_shortname": entry.get("bank_shortname"),
            },
        )

    def _atomic_write_accounts(self, accounts):
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        fd, tmp_path = tempfile.mkstemp(
            dir=BASE_DIR, prefix=".accounts-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
                f.write("\n")
            last_exc = None
            for _ in range(5):
                try:
                    os.replace(tmp_path, accounts_path)
                    return
                except OSError as exc:
                    last_exc = exc
                    time.sleep(0.2)
            raise last_exc
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ config
    def _label_known(self, label):
        accounts_path = os.path.join(BASE_DIR, "accounts.json")
        if not os.path.isfile(accounts_path):
            return False
        try:
            with open(accounts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        if not isinstance(data, list):
            return False
        return any(a.get("label") == label for a in data if isinstance(a, dict))

    def _set_next_override(self, label):
        directory = output_dir_from(self.config)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "next.json")
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".next-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"label": label, "set_at": time.time()}, f)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        # Clear this account's per-account cooldown so it is eligible now.
        try:
            out_path = os.path.join(
                directory, "{}.txt".format(sanitize_label(label))
            )
            if os.path.isfile(out_path):
                cooldown = self.config.get("account_cooldown_seconds", 180)
                stamp = time.time() - cooldown - 1
                os.utime(out_path, (stamp, stamp))
        except OSError:
            pass

    def _config_get(self):
        tabs = []
        for tab in CONFIG_SCHEMA:
            fields = []
            for field in tab["fields"]:
                value = _cfg_get(self.config, field["key"], field.get("default"))
                if field["type"] == "password":
                    # Secrets are write-only: never echo the stored value.
                    value = ""
                fields.append(
                    {
                        "key": field["key"],
                        "label": field["label"],
                        "type": field["type"],
                        "nullable": bool(field.get("nullable")),
                        "help": field.get("help", ""),
                        "placeholder": field.get("placeholder", ""),
                        "value": value,
                    }
                )
            tabs.append({"id": tab["id"], "title": tab["title"], "fields": fields})
        self._send_json(200, {"tabs": tabs})

    def _config_update(self):
        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json(400, {"error": "expected a JSON object body"})
            return
        updates = {}
        for key, field in CONFIG_FIELDS.items():
            if key not in body:
                continue
            # Secret fields are write-only: an empty submission keeps the
            # stored value unchanged.
            if field["type"] == "password" and not str(body[key] or ""):
                continue
            try:
                updates[key] = _coerce_field(field, body[key])
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
        if not updates:
            self._send_json(200, {"ok": True, "updated": None})
            return
        try:
            self._atomic_write_config(updates)
        except OSError as exc:
            self._send_json(500, {"error": "write failed: {}".format(exc)})
            return
        for key, value in updates.items():
            _cfg_set(self.config, key, value)
        # Never echo secret values back in the log or the response.
        safe = {
            key: ("***" if CONFIG_FIELDS[key]["type"] == "password" else value)
            for key, value in updates.items()
        }
        log(
            "[api] config updated: {}".format(
                ", ".join("{}={}".format(k, v) for k, v in safe.items())
            )
        )
        self._send_json(200, {"ok": True, "updated": safe})

    def _atomic_write_config(self, updates):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        for key, value in updates.items():
            _cfg_set(config, key, value)
        fd, tmp_path = tempfile.mkstemp(
            dir=BASE_DIR, prefix=".config-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, CONFIG_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ log tail
    def _log_tail(self, query):
        raw = (query.get("lines") or ["200"])[0]
        try:
            lines = int(raw)
        except (TypeError, ValueError):
            lines = 200
        lines = max(1, min(lines, 5000))

        log_file = log_file_from(self.config)
        if not log_file or not os.path.isfile(log_file):
            self._send_text(200, "")
            return
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
        except OSError:
            self._send_text(200, "")
            return
        tail = "\n".join(data.splitlines()[-lines:])
        self._send_text(200, tail + ("\n" if tail else ""))

    # ------------------------------------------------------------------ helpers
    def _send_text(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, reason):
        self._send_json(404, None)
        log("[api] 404 {} ({})".format(self.path, reason))

    def log_message(self, fmt, *args):
        log("[api] " + (fmt % args))


def main():
    config = load_config()
    host = config.get("api_host", "127.0.0.1")
    port = int(config.get("api_port", 8000))
    StatementHandler.config = config
    StatementHandler.manager = ProcessManager(BASE_DIR, config)
    server = ThreadingHTTPServer((host, port), StatementHandler)
    log("robot API listening on http://{}:{}/".format(host, port))
    log("routes: /health, /<bank>/<label>, /accounts, /config, /control/start|stop|status|log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
        StatementHandler.manager.stop()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
