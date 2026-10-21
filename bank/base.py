"""OS-level Chrome automation primitives shared by both bank flows.

Uses PyAutoGUI keyboard/mouse macros against a dedicated Chrome instance
launched via subprocess, so no WebDriver fingerprint is exposed.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

import pyautogui

from utils.clipboard import get_clipboard_text
from utils.output import log


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

    # ---------------------------------------------------------------- lifecycle
    def launch(self, url):
        """Start Chrome with a fresh profile at a fixed window size."""
        self.profile_dir = tempfile.mkdtemp(prefix="bca_bot_profile_")
        self._seed_no_password_manager()
        args = [
            self.config["chrome_exe"],
            "--user-data-dir={}".format(self.profile_dir),
            "--window-size={},{}".format(
                self.config["window_width"], self.config["window_height"]
            ),
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
        log("[{}] launching Chrome: {}".format(self.bank_name, url))
        self.process = subprocess.Popen(args)
        time.sleep(self.config["page_load_wait"])
        self.focus()

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

    # ---------------------------------------------------------------- focus/nav
    def focus(self):
        """Bring the Chrome window to the foreground by title."""
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

    def goto_url(self, url):
        """Focus the address bar and navigate to *url*."""
        self.focus()
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
        pyautogui.press("enter")
        time.sleep(self.config["delay_short"])

    def type_text(self, text):
        pyautogui.write(text, interval=0.05)
        time.sleep(self.config["delay_short"])

    # ---------------------------------------------------------------- login
    def keyboard_login(self, username, password):
        """Focus the page, Tab to the username field, then type credentials."""
        self.focus()
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
            screen = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
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
                        (max_loc[0] + width // 2, max_loc[1] + height // 2),
                        float(max_val),
                    )
            if hit is not None:
                return hit[0], hit[1]
            if time.time() >= deadline:
                return None, best
            time.sleep(0.5)

    def click_at(self, point):
        """Click an absolute screen coordinate (e.g. from ``locate_image``)."""
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
        self.focus()
        pyautogui.click(int(x), int(y))
        time.sleep(self.config["delay_short"])
        return True

    def click_image(self, name, timeout=None, confidence=None):
        """Locate and click an asset image, retrying until the timeout."""
        path = self.asset_path(name)
        if not os.path.exists(path):
            raise FileNotFoundError(
                "Asset image missing: {} (run capture mode to create it)".format(path)
            )
        confidence = confidence or self.config["image_confidence"]
        timeout = timeout if timeout is not None else self.config["image_timeout"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                loc = pyautogui.locateCenterOnScreen(path, confidence=confidence)
                if loc is not None:
                    pyautogui.click(loc)
                    time.sleep(self.config["delay_short"])
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        log("[{}] image not found within timeout: {}".format(self.bank_name, name))
        return False

    # ---------------------------------------------------------------- capture
    def select_all_copy(self):
        """Focus the page, then Ctrl+A and Ctrl+C."""
        self.focus()
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
