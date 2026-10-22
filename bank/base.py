"""OS-level Chrome automation primitives shared by both bank flows.

Uses PyAutoGUI keyboard/mouse macros against a dedicated Chrome instance
launched via subprocess, so no WebDriver fingerprint is exposed.
"""

import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import time

import pyautogui

from utils.clipboard import get_clipboard_text
from utils.output import log


def _enable_dpi_awareness():
    """Put screenshots and mouse coordinates on the same pixel grid (Windows).

    Without this the process is DPI-virtualized: ``pyautogui.screenshot()``
    returns physical pixels while ``pyautogui.click`` is interpreted in scaled
    coordinates, so a located image is clicked at the wrong spot. It is most
    obvious in a maximized window and on a VM whose display scaling is not 100%.
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


class ScrapeAborted(Exception):
    """Raised when a required page check fails and the run must stop.

    The account is not flagged as scraped: main.py clears its cooldown and
    moves on to the next account without saving anything.
    """


class ChromeDriver:
    """Launch and drive a dedicated Chrome instance with keyboard/mouse macros."""

    def __init__(self, config, bank_name):
        self.config = config
        self.bank_name = bank_name
        self.process = None
        self.profile_dir = None
        # Tracks whether the logout button image was located and clicked. When
        # False, the scrape is assumed not to have captured the statement: the
        # upload is skipped and the account's cooldown is cleared for a retry.
        self.logout_image_found = None
        # Last located captcha sample (path + solved text) when sample capture
        # is enabled; the bank flow confirms it after a successful login.
        self.last_captcha = None
        # Whether the screenshot->mouse coordinate scale was already reported.
        self._scale_logged = False
        # Whether the "window not found by pid" warning was already reported.
        self._handles_warned = False
        # Window handles of the Chrome instance this driver launched.
        self._own_handles = []

    # ---------------------------------------------------------------- lifecycle
    def launch(self, url):
        """Start Chrome with a fresh profile, maximized unless configured otherwise."""
        # A Chrome left open by the operator sits in front of the scraper's
        # window, steals the foreground and breaks the keyboard macros, so any
        # existing instance is closed first (config: close_existing_chrome).
        self.close_existing_chrome()
        self.profile_dir = tempfile.mkdtemp(prefix="bca_bot_profile_")
        self._seed_no_password_manager()
        width, height = self.window_geometry()
        # Macros (focus, form click, select-all, myBCA logout) derive coordinates
        # from these values, so keep them in sync with the real window.
        self.config["window_width"] = width
        self.config["window_height"] = height
        maximized = self.config.get("chrome_maximized", True)
        args = [
            self.config["chrome_exe"],
            "--user-data-dir={}".format(self.profile_dir),
        ]
        if maximized:
            args.append("--start-maximized")
        else:
            args.append("--window-size={},{}".format(width, height))
        args += [
            "--window-position=0,0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-notifications",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-save-password-bubble",
            "--disable-password-bubble",
            "--disable-features=PasswordManagerOnboarding,PasswordManagerSaveCredential",
            "--password-store=basic",
        ]
        proxy_ip = self.config.get("proxy_ip")
        proxy_port = self.config.get("proxy_port")
        if proxy_ip and proxy_port:
            args.append("--proxy-server=http://{}:{}".format(proxy_ip, proxy_port))
        args.append(url)
        log(
            "[{}] launching Chrome ({}): {}".format(
                self.bank_name,
                "maximized" if maximized else "{}x{}".format(width, height),
                url,
            )
        )
        # Windows that already existed before the launch, so the scraper's own
        # Chrome window can be identified by diffing afterwards.
        existing_handles = set(self._caption_handles())
        self.process = subprocess.Popen(args)
        time.sleep(self.config["page_load_wait"])
        new_handles = [
            hwnd for hwnd in self._caption_handles() if hwnd not in existing_handles
        ]
        own = [hwnd for hwnd in new_handles if self._window_pid(hwnd) == self.process.pid]
        self._own_handles = own or new_handles
        if self._own_handles:
            log(
                "[{}] tracking Chrome window(s): {}".format(
                    self.bank_name,
                    ", ".join(repr(self._window_title(h)) for h in self._own_handles),
                )
            )
        else:
            log(
                "[{}] could not spot the new Chrome window after launch; "
                "falling back to process/title matching".format(self.bank_name)
            )
        self.focus()
        if maximized:
            self.maximize()

    def _count_processes(self, image_name):
        """Number of running processes with this image name (0 on failure)."""
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq {}".format(image_name), "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
            )
        except Exception:
            return 0
        needle = image_name.lower()
        return sum(1 for line in output.splitlines() if needle in line.lower())

    def close_existing_chrome(self):
        """Close every running Chrome so no stray window hinders the scraper.

        The scraper always opens its own Chrome with a temporary profile; an
        operator's Chrome would be another window competing for the foreground,
        which breaks the mouse/keyboard macros. Controlled by the
        ``close_existing_chrome`` setting (default on).
        """
        if os.name != "nt" or not self.config.get("close_existing_chrome", True):
            return 0
        running = self._count_processes("chrome.exe")
        if running <= 0:
            return 0
        log(
            "[{}] closing {} running Chrome process(es) before launch".format(
                self.bank_name, running
            )
        )
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as exc:
            log("[{}] closing existing Chrome failed: {}".format(self.bank_name, exc))
            return running
        # Give Windows a moment to destroy the windows and release the desktop.
        time.sleep(1.0)
        remaining = self._count_processes("chrome.exe")
        if remaining:
            log(
                "[{}] {} Chrome process(es) are still running after taskkill".format(
                    self.bank_name, remaining
                )
            )
        return running

    def window_geometry(self):
        """Return the (width, height) the Chrome window occupies."""
        if self.config.get("chrome_maximized", True):
            try:
                width, height = pyautogui.size()
                if width and height:
                    return int(width), int(height)
            except Exception:
                log(
                    "[{}] could not read the screen size; using window_width/window_height".format(
                        self.bank_name
                    )
                )
        return int(self.config["window_width"]), int(self.config["window_height"])

    def maximize(self):
        """Maximize the Chrome window (in addition to --start-maximized)."""
        handles = self._window_handles()
        if handles:
            user32 = ctypes.windll.user32
            maximized = False
            for hwnd in handles:
                try:
                    user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                    maximized = True
                except Exception:
                    continue
            if maximized:
                time.sleep(self.config["delay_short"])
                return True
        hint = self.config.get("window_title_hint", "Google Chrome")
        try:
            for win in reversed(pyautogui.getWindowsWithTitle(hint)):
                if not win.title:
                    continue
                try:
                    if win.isMinimized:
                        win.restore()
                    win.maximize()
                    time.sleep(self.config["delay_short"])
                    return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _seed_no_password_manager(self):
        """Pre-write Chrome's Preferences to disable the password manager.

        This suppresses the "save username/password?" bubble that appears
        after login. Writes ``credentials_enable_service`` and the profile
        password-manager toggles into ``Default/Preferences`` before Chrome
        first starts on the fresh profile.
        """
        if not self.profile_dir:
            return
        try:
            default_dir = os.path.join(self.profile_dir, "Default")
            os.makedirs(default_dir, exist_ok=True)
            pref_path = os.path.join(default_dir, "Preferences")
            pref = {}
            if os.path.exists(pref_path):
                try:
                    with open(pref_path, "r", encoding="utf-8") as f:
                        pref = json.load(f)
                except (OSError, ValueError):
                    pref = {}
            pref["credentials_enable_service"] = False
            profile = pref.setdefault("profile", {})
            profile["password_manager_enabled"] = False
            profile["password_generation_enabled"] = False
            profile["password_manager_leak_detection"] = False
            with open(pref_path, "w", encoding="utf-8") as f:
                json.dump(pref, f)
        except OSError:
            pass

    def close(self):
        """Terminate Chrome and remove the temp profile directory."""
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass
            try:
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self.profile_dir and os.path.isdir(self.profile_dir):
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            self.profile_dir = None
        self._own_handles = []

    # ---------------------------------------------------------------- focus/nav
    def _window_title(self, hwnd):
        """Title of one window handle ('' when unavailable)."""
        try:
            user32 = ctypes.windll.user32
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            return buffer.value
        except Exception:
            return ""

    def _window_pid(self, hwnd):
        """Process id that owns a window handle (0 when unavailable)."""
        try:
            from ctypes import wintypes

            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value
        except Exception:
            return 0

    def _caption_handles(self):
        """Visible top-level windows that carry a title bar, for any process."""
        if os.name != "nt":
            return []
        try:
            from ctypes import wintypes
        except Exception:
            return []
        user32 = ctypes.windll.user32
        handles = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowLongW(
                hwnd, -16
            ) & 0x00C00000:
                handles.append(hwnd)
            return True

        try:
            user32.EnumWindows(callback_type(callback), 0)
        except Exception:
            return []
        return handles

    def _window_handles(self):
        """Visible top-level window handles of the Chrome instance we launched.

        The window is remembered from the launch (handles that appeared while
        Chrome started), because Chrome does not always keep the process we
        spawned as the window owner. Process id and finally title matching are
        used as fallbacks, and title matching alone also finds the operator's
        own Chrome, hence it is last.
        """
        if os.name != "nt":
            return []
        if self._own_handles:
            user32 = ctypes.windll.user32
            alive = []
            for hwnd in self._own_handles:
                try:
                    if user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
                        alive.append(hwnd)
                except Exception:
                    alive.append(hwnd)
            if alive:
                return alive
        if self.process is None:
            return []
        try:
            from ctypes import wintypes
        except Exception:
            return []
        user32 = ctypes.windll.user32
        pid = self.process.pid
        handles = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowLongW(hwnd, -16) & 0x00C00000:  # WS_CAPTION
                handles.append(hwnd)
            return True

        try:
            user32.EnumWindows(callback_type(callback), 0)
        except Exception:
            return []
        return handles

    def _activate(self, hwnd):
        """Bring one window to the foreground, retrying the way Windows allows."""
        user32 = ctypes.windll.user32
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            time.sleep(self.config["delay_short"])
            if user32.GetForegroundWindow() == hwnd:
                return True
            # Windows can refuse SetForegroundWindow for a background process;
            # a click on the title bar brings the window forward for good.
            from ctypes import wintypes

            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                x = (rect.left + rect.right) // 2
                y = max(1, rect.top + 8)
                pyautogui.click(x, y)
                time.sleep(self.config["delay_short"])
                return user32.GetForegroundWindow() == hwnd
        except Exception:
            pass
        return False

    def focus(self):
        """Bring the scraper's own Chrome window to the foreground."""
        for hwnd in self._window_handles():
            if self._activate(hwnd):
                return True
        hint = self.config.get("window_title_hint", "Google Chrome")
        try:
            for win in reversed(pyautogui.getWindowsWithTitle(hint)):
                if not win.title:
                    continue
                try:
                    if win.isMinimized:
                        win.restore()
                    win.activate()
                    time.sleep(self.config["delay_short"])
                    return True
                except Exception:
                    continue
        except Exception:
            pass
        # Fallback: click near the top of the window area.
        try:
            pyautogui.click(self.config["window_width"] // 2, 40)
        except Exception:
            pass
        return True

    def _foreground_window_title(self):
        """Title of the current foreground window ('' when unavailable)."""
        if os.name != "nt":
            return ""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return ""
        return self._window_title(hwnd) if hwnd else ""

    def ensure_foreground(self):
        """Return True when our Chrome window is the active window."""
        handles = self._window_handles()
        if not handles:
            if not self._handles_warned:
                self._handles_warned = True
                log(
                    "[{}] cannot identify the scraper's Chrome window by process; "
                    "falling back to title matching (foreground is {!r})".format(
                        self.bank_name, self._foreground_window_title()
                    )
                )
            return True
        try:
            if ctypes.windll.user32.GetForegroundWindow() in handles:
                return True
        except Exception:
            return True
        if self.focus():
            return True
        log(
            "[{}] Chrome window could not be activated; foreground is {!r}".format(
                self.bank_name, self._foreground_window_title()
            )
        )
        return False

    def clear_focused_field(self):
        """Select and delete the text of the focused input (Ctrl+A, Delete)."""
        self.ensure_foreground()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(self.config["delay_short"] * 0.5)
        pyautogui.press("delete")
        time.sleep(self.config["delay_short"] * 0.5)

    def goto_url(self, url):
        """Focus the address bar and navigate to *url*."""
        self.ensure_foreground()
        pyautogui.hotkey("ctrl", "l")
        time.sleep(self.config["delay_short"])
        pyautogui.write(url, interval=0.02)
        pyautogui.press("enter")
        time.sleep(self.config["page_load_wait"])

    def tab(self, count=1):
        for _ in range(max(0, count)):
            pyautogui.press("tab")
            time.sleep(0.15)

    def press_enter(self):
        self.ensure_foreground()
        pyautogui.press("enter")
        time.sleep(self.config["delay_short"])

    def type_text(self, text):
        self.ensure_foreground()
        pyautogui.write(text, interval=0.05)
        time.sleep(self.config["delay_short"])

    # ---------------------------------------------------------------- login
    def keyboard_login(self, username, password):
        """Focus the page, Tab to the username field, then type credentials."""
        self.ensure_foreground()
        w = self.config["window_width"]
        h = self.config["window_height"]
        click_x = self.config.get("form_click_x", w // 2)
        click_y = self.config.get("form_click_y", int(h * 0.22))
        pyautogui.click(click_x, click_y)
        time.sleep(self.config["delay_short"])
        self.tab(self.config.get("tabs_to_username", 1))
        self.type_text(username)
        self.tab(1)
        self.type_text(password)
        time.sleep(self.config["delay_short"])

    def submit(self, button_image="login_button.png"):
        """Submit via Enter, falling back to an image-matched button click."""
        self.ensure_foreground()
        pyautogui.press("enter")
        time.sleep(self.config["delay_long"])
        asset = self.asset_path(button_image)
        if os.path.exists(asset) and self._image_present(asset, tries=1):
            log(
                "[{}] Enter did not submit; clicking login button image".format(
                    self.bank_name
                )
            )
            self.click_image(button_image, timeout=self.config["delay_long"])
            time.sleep(self.config["delay_long"])
        self.handle_challenge()

    def handle_challenge(self):
        """Pause for manual completion if a challenge screen is detected."""
        asset = self.asset_path("challenge.png")
        if os.path.exists(asset) and self._image_present(asset, tries=2):
            log(
                "[{}] challenge screen detected; manual step required".format(
                    self.bank_name
                )
            )
            input(
                "Complete the challenge manually in the browser, "
                "then press Enter to continue..."
            )
            time.sleep(self.config["delay_short"])
            return True
        return False

    # ---------------------------------------------------------------- images
    def asset_path(self, name):
        """On-disk path for an asset reference.

        Accepts a bare file name (resolved inside ``assets/<bank>/``) or a
        path that already includes directories, so a config may store either
        form.
        """
        if os.path.isabs(name) or "/" in name or "\\" in name:
            return name
        return os.path.join(self.config["assets_dir"], self.bank_name, name)

    def _mouse_scale(self, shot):
        """Return (sx, sy) converting screenshot pixels to mouse coordinates.

        Normally both grids match (1.0) once the process is DPI aware; the ratio
        is applied anyway so a virtualized session cannot shift every click.
        """
        try:
            width, height = shot.size
            mouse_w, mouse_h = pyautogui.size()
            if width and height:
                scale_x = mouse_w / float(width)
                scale_y = mouse_h / float(height)
                if not self._scale_logged:
                    self._scale_logged = True
                    if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
                        log(
                            "[{}] display scaling detected: screenshot {}x{} -> "
                            "mouse {}x{} (applying {:.3f}x{:.3f})".format(
                                self.bank_name,
                                width,
                                height,
                                mouse_w,
                                mouse_h,
                                scale_x,
                                scale_y,
                            )
                        )
                return scale_x, scale_y
        except Exception:
            pass
        return 1.0, 1.0

    def locate_image(self, name, timeout=None, confidence=None, scales=None):
        """Locate an asset image on screen, tolerating a capture scale offset.

        Reference images are sometimes saved from a screenshot taken at a
        different display scale, in which case a plain match never reaches the
        confidence threshold. The template is tried at its saved size first,
        then at each factor in *scales*.

        Returns ``(center, score)``: *center* is an ``(x, y)`` tuple when a
        match at or above ``confidence`` was found (else ``None``), and
        *score* is the best normalized score seen either way.
        """
        path = self.asset_path(name)
        if not os.path.exists(path):
            log("[{}] reference image missing: {}".format(self.bank_name, path))
            return None, 0.0
        confidence = confidence or self.config["image_confidence"]
        timeout = timeout if timeout is not None else self.config["image_timeout"]
        factors = tuple(scales) if scales else (1.0,)

        import cv2
        import numpy as np

        base = cv2.imread(path)
        if base is None:
            log("[{}] cannot read reference image: {}".format(self.bank_name, path))
            return None, 0.0
        templates = []
        for factor in factors:
            if factor == 1.0:
                template = base
            else:
                template = cv2.resize(
                    base, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA
                )
            if template.shape[0] < 8 or template.shape[1] < 8:
                continue
            templates.append(template)

        deadline = time.time() + timeout
        best = 0.0
        while True:
            shot = pyautogui.screenshot()
            screen = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
            scale_x, scale_y = self._mouse_scale(shot)
            hit = None
            for template in templates:
                if (
                    template.shape[0] > screen.shape[0]
                    or template.shape[1] > screen.shape[1]
                ):
                    continue
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                best = max(best, float(max_val))
                if max_val >= confidence and (hit is None or max_val > hit[1]):
                    height, width = template.shape[:2]
                    hit = (
                        (
                            int(round((max_loc[0] + width // 2) * scale_x)),
                            int(round((max_loc[1] + height // 2) * scale_y)),
                        ),
                        float(max_val),
                    )
            if hit is not None:
                return hit[0], hit[1]
            if time.time() >= deadline:
                return None, best
            time.sleep(0.5)

    def locate_image_by_scrolling(
        self,
        name,
        step=100,
        max_steps=20,
        probe_timeout=0.8,
        confidence=None,
        scales=None,
        wheel_px=100,
        reset=True,
    ):
        """Locate an image on a page by scrolling down in small increments.

        :meth:`locate_image` only sees what is currently rendered, so an
        element below the fold (e.g. the PERMATA statement flag) is never
        found. This scrolls down *step* pixels at a time (one wheel notch is
        about *wheel_px*), probing after each step, and stops when the image
        appears, when the page stops moving (bottom reached), or after
        *max_steps* increments.

        Returns ``(center, score)`` like :meth:`locate_image`; *center* is the
        image position on screen, *score* the best match seen at any position.
        """
        center, score = self.locate_image(
            name, timeout=probe_timeout, confidence=confidence, scales=scales
        )
        best = score
        if center is not None:
            return center, best
        if step <= 0 or max_steps <= 0:
            return None, best

        self.ensure_foreground()
        if reset:
            # Start from the top so a late-rendering element is not skipped.
            self.scroll_to_top()

        method = None
        moved_before = False
        for index in range(1, max_steps + 1):
            method = self.scroll_page(
                direction=1,
                step_px=step,
                method=method,
                wheel_px=wheel_px,
                allow_click=not moved_before,
            )
            if method is None:
                if moved_before:
                    log(
                        "[{}] reached the bottom while looking for {}".format(
                            self.bank_name, name
                        )
                    )
                else:
                    log(
                        "[{}] could not scroll the page while looking for {} "
                        "(no wheel or key event moved it; foreground is {!r})".format(
                            self.bank_name, name, self._foreground_window_title()
                        )
                    )
                break
            moved_before = True
            log(
                "[{}] scrolled via {} (step {}/{}) looking for {}".format(
                    self.bank_name, method, index, max_steps, name
                )
            )
            center, score = self.locate_image(
                name, timeout=probe_timeout, confidence=confidence, scales=scales
            )
            best = max(best, score)
            if center is not None:
                return center, best
        return None, best

    def scroll_page(self, direction=1, step_px=100, method=None, wheel_px=100, allow_click=False):
        """Scroll the visible page by about *step_px* and confirm it moved.

        ``PageDown`` is the primary method (the PERMATA statement page ignores
        the mouse wheel but scrolls from the keyboard), followed by the wheel
        over a few points and the arrow keys. If the keyboard does nothing the
        page is clicked once to give the document focus and ``PageDown`` is
        retried — the same sequence a person uses by hand. *direction* is +1
        down, -1 up. The name of the method that actually moved the page is
        returned (``pagedown``/``pageup``, ``wheel`` or ``arrows``), or ``None``
        when nothing moved.

        *method* is the previous successful method; it is retried first so the
        remaining steps stay fast.
        """
        notches = max(1, int(round(float(step_px) / float(max(1, wheel_px)))))
        width = self.config["window_width"]
        height = self.config["window_height"]
        page_key = "pagedown" if direction > 0 else "pageup"
        arrow_key = "down" if direction > 0 else "up"
        arrow_presses = max(1, int(step_px) // 40)
        clicks = -notches if direction > 0 else notches
        before = self._screen_signature()

        def moved():
            time.sleep(self.config["delay_short"])
            return self._screen_signature() != before

        def press_page():
            try:
                pyautogui.press(page_key)
                return moved()
            except Exception:
                return False

        def press_arrows():
            try:
                pyautogui.press(arrow_key, presses=arrow_presses)
                return moved()
            except Exception:
                return False

        def press_wheel():
            for x, y in (
                (width // 2, height // 2),
                (int(width * 0.3), height // 2),
                (width // 2, int(height * 0.75)),
            ):
                try:
                    pyautogui.scroll(clicks, x=x, y=y)
                except Exception:
                    continue
                if moved():
                    return True
            return False

        self.ensure_foreground()
        if method == page_key and press_page():
            return page_key
        if method == "arrows" and press_arrows():
            return "arrows"

        if press_page():
            return page_key

        if allow_click:
            # The keyboard went nowhere at the very first step: the document
            # may not have focus (address bar or another control). Click the
            # content once and try PageDown again, like the manual workaround.
            try:
                self.click_at((width // 2, height // 2))
                log(
                    "[{}] page did not react to the keyboard; clicked it to "
                    "focus and retried PageDown".format(self.bank_name)
                )
            except Exception:
                pass
            if press_page():
                return page_key

        if press_wheel():
            return "wheel"
        if press_arrows():
            return "arrows"
        return None

    def _screen_signature(self):
        """Cheap fingerprint of the visible page, used to detect scrolling."""
        try:
            shot = pyautogui.screenshot()
            return shot.resize((64, 36)).convert("L").tobytes()
        except Exception:
            return b""

    def scroll_to_top(self):
        """Scroll the focused page back to the top, without touching the mouse."""
        try:
            self.ensure_foreground()
            pyautogui.hotkey("ctrl", "home")
            time.sleep(self.config["delay_short"])
            return True
        except Exception:
            return False

    def click_at(self, point):
        """Focus our Chrome window and click an absolute screen coordinate."""
        self.ensure_foreground()
        pyautogui.click(int(point[0]), int(point[1]))
        time.sleep(self.config["delay_short"])
        return True

    def locate_image_candidates(
        self, name, limit=10, timeout=None, confidence=None, scales=None, blur=None
    ):
        """Locate up to *limit* candidate matches, best-first.

        Like ``locate_image`` but returns several distinct matches (non-maximum
        suppressed) as ``[((x, y), score, (width, height)), ...]`` where
        width/height are the size of the template at the scale that matched.
        Used when one template can match several places (e.g. a captcha whose
        text changes) so the caller can validate each candidate and pick the
        right one. Returns ``[]`` when nothing matches before *timeout*.

        *blur* (odd pixel size) Gaussian-blurs both the template and the screen
        before matching, so a template whose fine detail changes (e.g. captcha
        letters) still matches on its broader background pattern.
        """
        path = self.asset_path(name)
        if not os.path.exists(path):
            log("[{}] reference image missing: {}".format(self.bank_name, path))
            return []
        confidence = (
            confidence if confidence is not None else self.config["image_confidence"]
        )
        timeout = timeout if timeout is not None else self.config["image_timeout"]
        factors = tuple(scales) if scales else (1.0,)
        blur = int(blur) if blur else 0
        if blur and blur % 2 == 0:
            blur += 1

        import cv2
        import numpy as np

        base = cv2.imread(path)
        if base is None:
            log("[{}] cannot read reference image: {}".format(self.bank_name, path))
            return []
        templates = []
        for factor in factors:
            if factor == 1.0:
                template = base
            else:
                template = cv2.resize(
                    base, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA
                )
            if template.shape[0] < 8 or template.shape[1] < 8:
                continue
            if blur >= 3:
                template = cv2.GaussianBlur(template, (blur, blur), 0)
            templates.append(template)

        deadline = time.time() + timeout
        while True:
            screen = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
            if blur >= 3:
                screen = cv2.GaussianBlur(screen, (blur, blur), 0)
            peaks = []
            for template in templates:
                if (
                    template.shape[0] > screen.shape[0]
                    or template.shape[1] > screen.shape[1]
                ):
                    continue
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                height, width = template.shape[:2]
                flat = result.ravel()
                top_k = min(64, flat.size)
                top = np.argpartition(flat, -top_k)[-top_k:]
                for index in top:
                    value = float(flat[index])
                    if value < confidence:
                        continue
                    row, col = divmod(int(index), result.shape[1])
                    peaks.append(
                        (value, col + width // 2, row + height // 2, width, height)
                    )
            if peaks:
                peaks.sort(key=lambda peak: peak[0], reverse=True)
                picked = []
                for value, cx, cy, width, height in peaks:
                    clash = any(
                        abs(cx - px) < (width + pw) // 2
                        and abs(cy - py) < (height + ph) // 2
                        for _, px, py, pw, ph in picked
                    )
                    if not clash:
                        picked.append((value, cx, cy, width, height))
                    if len(picked) >= limit:
                        break
                return [
                    ((cx, cy), value, (width, height))
                    for value, cx, cy, width, height in picked
                ]
            if time.time() >= deadline:
                return []
            time.sleep(0.5)

    def _image_present(self, path, tries=1, confidence=None):
        confidence = confidence or self.config["image_confidence"]
        for _ in range(tries):
            try:
                if pyautogui.locateCenterOnScreen(path, confidence=confidence) is not None:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def image_present(self, name, timeout=None, confidence=None):
        """Poll for an asset image on screen, returning True once it appears.

        Returns False when the asset file is missing or the image is not
        located before *timeout* seconds elapse.
        """
        path = self.asset_path(name)
        if not os.path.exists(path):
            log("[{}] reference image missing: {}".format(self.bank_name, path))
            return False
        confidence = confidence or self.config["image_confidence"]
        timeout = timeout if timeout is not None else self.config["image_timeout"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if pyautogui.locateCenterOnScreen(path, confidence=confidence) is not None:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def click_point(self, x, y):
        """Focus the window and click an absolute screen coordinate."""
        self.ensure_foreground()
        pyautogui.click(int(x), int(y))
        time.sleep(self.config["delay_short"])
        return True

    def click_image(self, name, timeout=None, confidence=None):
        """Locate and click an asset image, retrying until the timeout.

        Goes through the shared locator so the click uses the same coordinate
        mapping and window activation as every other bank step.
        """
        path = self.asset_path(name)
        if not os.path.exists(path):
            raise FileNotFoundError(
                "Asset image missing: {} (run capture mode to create it)".format(path)
            )
        center, score = self.locate_image(
            name,
            timeout=timeout if timeout is not None else self.config["image_timeout"],
            confidence=confidence,
        )
        if center is None:
            log(
                "[{}] image not found within timeout: {} (best score {:.2f})".format(
                    self.bank_name, name, score
                )
            )
            return False
        log("[{}] clicking {} (score {:.2f})".format(self.bank_name, name, score))
        self.click_at(center)
        return True

    # ---------------------------------------------------------------- capture
    def select_all_copy(self):
        """Focus the page, then Ctrl+A and Ctrl+C."""
        self.ensure_foreground()
        w = self.config["window_width"]
        h = self.config["window_height"]
        pyautogui.click(w // 2, h // 2)
        time.sleep(self.config["delay_short"])
        pyautogui.hotkey("ctrl", "a")
        time.sleep(self.config["delay_short"])
        pyautogui.hotkey("ctrl", "c")
        time.sleep(self.config["delay_short"])

    def capture_statement_text(self, label):
        """Select-all/copy the page and return the captured statement text.

        The text is NOT written to disk here: the account's .txt file is only
        saved after the backoffice process succeeds (see main.py), so a failed
        or incomplete scrape never advances the account's cooldown.
        """
        self.select_all_copy()
        text = get_clipboard_text()
        if not text:
            log("[{}] clipboard empty on first try; retrying".format(self.bank_name))
            self.select_all_copy()
            text = get_clipboard_text()
        if not text:
            raise RuntimeError("clipboard empty after Ctrl+A/Ctrl+C; statement not captured")
        return text

    def screenshot(self, name):
        """Save a debug screenshot for troubleshooting."""
        debug_dir = os.path.join(self.config["output_dir"], "debug")
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, name)
        try:
            pyautogui.screenshot(path)
        except Exception:
            pass
        return path
