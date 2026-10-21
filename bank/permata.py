"""PERMATA flow: login at https://www.permatanet.com/pnet/.

Steps (all waits/images configurable via config.json "permata_*"):
1. Close the landing-page modal via ``permata_close_button`` (default
   ``close_button.JPG``): locate it, wait ``permata_close_wait``, click it.
2. Log in: click the username field image (``permata_user_id_images``, default
   ``user_id1.JPG``/``user_id2.JPG`` — Indonesian or English label), type the
   username, Tab to the password, type it, Tab to the captcha box, solve the
   4-letter captcha by OCR, submit. On failure the captcha is refreshed and
   retried up to ``permata_captcha_attempts`` times.
3. Confirm login by the user-icon gate (``permata_user_icon``, default
   ``user_icon.JPG``). Its middle letters vary, so it is matched at
   ``permata_icon_confidence``. When it is not found the account is aborted
   (``ScrapeAborted`` → cooldown cleared, not flagged scraped, next account).
4. Wait ``permata_after_login_wait``, open ``permata_statement_url`` (default
   ``.../saving-detail/IDR#mutation``), wait for the statement flag image
   (``permata_ind_flag``, default ``ind_flag.JPG``), wait
   ``permata_ind_flag_wait`` and click it.
5. Wait ``permata_statement_wait`` for the statement to load, capture it with
   Ctrl+A / Ctrl+C, then wait ``permata_capture_wait``.
6. Log out: click the user icon, wait ``permata_logout_open_wait``, then click
   the logout button (``permata_logout_button``, default
   ``logout_btn_permata.JPG``). If either image is not found the account is not
   saved: main.py clears the cooldown and moves on to the next account
   (``logout_image_found`` False).

The changed statement is then uploaded to the backoffice like the other banks.
"""

import os
import time

from bank.base import ChromeDriver, ScrapeAborted
from utils import captcha_dataset
from utils.captcha import read_captcha, read_captcha_near, read_captcha_permata
from utils.output import log

DEFAULT_LOGIN_URL = "https://www.permatanet.com/pnet/"
DEFAULT_STATEMENT_URL = "https://www.permatanet.com/pnet/saving-detail/IDR#mutation"


class Permata:
    def __init__(self, config):
        self.config = config
        self.driver = ChromeDriver(config, "permata")

    def run(self, account, capture_mode=False):
        login_url = self.config.get("permata_login_url", DEFAULT_LOGIN_URL)

        self.driver.launch(login_url)

        if capture_mode:
            input(
                "Capture mode [permata]: save assets/permata/ reference images "
                "(close_button.JPG, user_id1.JPG/user_id2.JPG, captcha.JPG, "
                "captcha refresh image, user_icon.JPG, ind_flag.JPG, "
                "logout_btn_permata.JPG) and note the captcha screen region, "
                "then press Enter to continue..."
            )
            return None

        self._close_landing_modal()
        self._login(account["username"], account["password"])

        after_login_wait = self.config.get("permata_after_login_wait", 3.0)
        log("[permata] waiting {:.1f}s after login".format(after_login_wait))
        time.sleep(after_login_wait)

        statement_url = self.config.get(
            "permata_statement_url", DEFAULT_STATEMENT_URL
        )
        log("[permata] opening the statement page: {}".format(statement_url))
        self.driver.goto_url(statement_url)

        self._open_statement()

        statement_wait = self.config.get("permata_statement_wait", 8.0)
        log(
            "[permata] waiting {:.1f}s for the statement to load".format(
                statement_wait
            )
        )
        time.sleep(statement_wait)

        text = self.driver.capture_statement_text(account["label"])

        capture_wait = self.config.get("permata_capture_wait", 3.0)
        log("[permata] waiting {:.1f}s before logout".format(capture_wait))
        time.sleep(capture_wait)

        try:
            self._logout()
        except Exception as exc:
            log("[permata] logout failed: {}".format(exc))

        return text

    # ------------------------------------------------------------------- login
    def _close_landing_modal(self):
        """Close the landing-page modal via its close button image.

        The landing page opens a modal on arrival; locate its close button,
        wait ``permata_close_wait`` seconds, then click it. Best-effort: when
        the button is not found it is logged and the flow continues.
        """
        image = self.config.get("permata_close_button", "close_button.JPG")
        center, score = self.driver.locate_image(
            image, timeout=self._image_timeout(), scales=self._scales()
        )
        if center is None:
            log(
                "[permata] landing modal close button not found ({}; score "
                "{:.2f})".format(image, score)
            )
            return
        log(
            "[permata] landing modal close button found ({}; score {:.2f})".format(
                image, score
            )
        )
        close_wait = self.config.get("permata_close_wait", 3.0)
        log("[permata] waiting {:.1f}s before closing the modal".format(close_wait))
        time.sleep(close_wait)
        self.driver.click_at(center)

    def _focus_username(self):
        """Click the username field image (Indonesian or English label)."""
        images = self.config.get(
            "permata_user_id_images", ["user_id1.JPG", "user_id2.JPG"]
        )
        if isinstance(images, str):
            images = [part.strip() for part in images.split(",") if part.strip()]
        best = 0.0
        for name in images:
            if not os.path.exists(self.driver.asset_path(name)):
                log("[permata] username field image missing: {}".format(name))
                continue
            center, score = self.driver.locate_image(
                name, timeout=self._image_timeout(), scales=self._scales()
            )
            best = max(best, score)
            if center is not None:
                log(
                    "[permata] clicking the username field ({}; score "
                    "{:.2f})".format(name, score)
                )
                self.driver.click_at(center)
                return
        raise ScrapeAborted(
            "permata username field not found ({}; best score {:.2f})".format(
                ", ".join(images), best
            )
        )

    def _login(self, username, password):
        """Type credentials, solve the captcha by OCR, submit, retry on failure.

        Each attempt OCRs the captcha, types it and submits. On failure the
        captcha is refreshed and the next attempt runs. After
        ``permata_captcha_attempts`` failures the account is aborted.
        """
        login_wait = self.config.get("permata_login_wait", 5.0)
        log("[permata] waiting {:.1f}s for the login form".format(login_wait))
        time.sleep(login_wait)

        # Focus the username field by clicking its image (the label can be
        # Indonesian or English, hence two reference images), type the
        # username, Tab to the password, type it, then Tab to the captcha box.
        self._focus_username()
        self.driver.type_text(username)
        self.driver.tab(1)
        self.driver.type_text(password)
        self.driver.tab(1)

        attempts = self.config.get("permata_captcha_attempts", 2)
        dashboard_wait = self.config.get("permata_dashboard_wait", 7.0)
        retry_wait = self.config.get("permata_captcha_retry_wait", 3.0)
        for attempt in range(1, attempts + 1):
            # Drop any sample from a previous (rejected) attempt so that, on
            # success, only the captcha actually submitted gets labeled.
            self.driver.last_captcha = None
            captcha = self._read_captcha()
            if captcha:
                log(
                    "[permata] attempt {}/{}: typing captcha".format(attempt, attempts)
                )
                self.driver.type_text(captcha)
            else:
                log(
                    "[permata] attempt {}/{}: captcha OCR failed".format(
                        attempt, attempts
                    )
                )
            self.driver.press_enter()
            # Wait for the login to resolve. After a failed attempt the next
            # captcha only needs a short pause, so use the shorter retry wait
            # until the final attempt, which keeps the full dashboard wait.
            wait = retry_wait if attempt < attempts else dashboard_wait
            log("[permata] waiting {:.1f}s for login result".format(wait))
            time.sleep(wait)
            if self._logged_in():
                log("[permata] logged in on attempt {}".format(attempt))
                self._confirm_captcha_sample()
                self.driver.handle_challenge()
                return
            log("[permata] login not confirmed on attempt {}".format(attempt))
            if attempt < attempts:
                self._refresh_captcha()

        raise ScrapeAborted(
            "permata login failed after {} captcha attempt(s)".format(attempts)
        )

    def _confirm_captcha_sample(self):
        """Label the last captured captcha after a successful login.

        When ``permata_capture_samples`` is on, ``read_captcha_near`` saved the
        located crop and the solved text on the driver. A successful login means
        the submitted text was accepted, i.e. a perfectly case-labeled sample;
        append it to ``dataset/permata/labels.txt``.
        """
        info = getattr(self.driver, "last_captcha", None)
        if not info:
            return
        self.driver.last_captcha = None
        try:
            row = captcha_dataset.confirm_sample(
                info.get("path"), info.get("text"), self.config
            )
        except Exception as exc:
            log("[permata] confirming captcha sample failed: {}".format(exc))
            return
        if row:
            log("[permata] labeled captcha sample {}".format(row[0]))

    def _logged_in(self):
        """True when the logged-in gate image (user icon) is on screen."""
        image = self.config.get("permata_user_icon", "user_icon.JPG")
        center, score = self.driver.locate_image(
            image,
            timeout=self._image_timeout(),
            confidence=self._icon_confidence(),
            scales=self._scales(),
        )
        log(
            "[permata] login gate (user icon) {} (score {:.2f})".format(
                "found" if center is not None else "not found", score
            )
        )
        return center is not None

    def _read_captcha(self):
        """Solve the captcha case-accurately, then fall back to the region.

        Uses ``read_captcha_permata`` (ddddocr letters + font/Tesseract case
        resolution, no training) to locate the captcha by its reference image;
        if that fails, retries against the configured fixed screen region.
        """
        solver = lambda shot: read_captcha_permata(shot, self.config)
        text = read_captcha_near(
            self.driver,
            self.config,
            timeout=self._image_timeout(),
            solver=solver,
        )
        if text:
            return text
        return read_captcha(self.config, solver=solver, driver=self.driver)

    def _refresh_captcha(self):
        """Click the captcha image to request a fresh code for the next attempt."""
        image = self.config.get(
            "permata_captcha_refresh_image", "captcha_refresh.png"
        )
        center, score = self.driver.locate_image(
            image, timeout=self._image_timeout(), scales=self._scales()
        )
        if center is None:
            log(
                "[permata] captcha refresh image not found ({}; score "
                "{:.2f})".format(image, score)
            )
            return
        log(
            "[permata] refreshing captcha via {} (score {:.2f})".format(
                image, score
            )
        )
        self.driver.click_at(center)

    # ---------------------------------------------------------------- helpers
    def _image_timeout(self):
        return self.config.get(
            "permata_page_timeout", self.config.get("image_timeout", 15)
        )

    def _scales(self):
        return self.config.get(
            "permata_image_scales", [1.0, 0.8, 0.67, 0.5, 1.25, 1.5]
        )

    def _icon_confidence(self):
        """Match threshold for the user icon (its middle letters vary)."""
        return self.config.get("permata_icon_confidence", 0.7)

    # ------------------------------------------------------------- statement
    def _open_statement(self):
        """Wait for the statement flag image, then click it to load mutations.

        Best-effort: when the flag image is not found it is logged and the flow
        continues to the statement wait.
        """
        image = self.config.get("permata_ind_flag", "ind_flag.JPG")
        center, score = self.driver.locate_image(
            image, timeout=self._image_timeout(), scales=self._scales()
        )
        if center is None:
            log(
                "[permata] statement flag image not found ({}; score "
                "{:.2f}); continuing".format(image, score)
            )
            return
        log("[permata] statement flag found ({}; score {:.2f})".format(image, score))
        wait = self.config.get("permata_ind_flag_wait", 3.0)
        log("[permata] waiting {:.1f}s before clicking the flag".format(wait))
        time.sleep(wait)
        self.driver.click_at(center)

    # ---------------------------------------------------------------- logout
    def _logout(self):
        """Log out: click the user icon, then the logout button image.

        Sets ``driver.logout_image_found`` False when either image is not found
        so main.py leaves the account un-flagged (cooldown cleared, not saved)
        and moves on to the next account.
        """
        icon = self.config.get("permata_user_icon", "user_icon.JPG")
        button = self.config.get("permata_logout_button", "logout_btn_permata.JPG")
        self.driver.logout_image_found = False

        center, score = self.driver.locate_image(
            icon,
            timeout=self._image_timeout(),
            confidence=self._icon_confidence(),
            scales=self._scales(),
        )
        if center is None:
            log(
                "[permata] logout: user icon not found ({}; score {:.2f})".format(
                    icon, score
                )
            )
            return
        log(
            "[permata] opening the logout menu via {} (score {:.2f})".format(
                icon, score
            )
        )
        self.driver.click_at(center)

        open_wait = self.config.get("permata_logout_open_wait", 2.0)
        log("[permata] waiting {:.1f}s for the logout menu".format(open_wait))
        time.sleep(open_wait)

        center, score = self.driver.locate_image(
            button, timeout=self._image_timeout(), scales=self._scales()
        )
        if center is None:
            log(
                "[permata] logout button not found ({}; score {:.2f})".format(
                    button, score
                )
            )
            return
        self.driver.logout_image_found = True
        log("[permata] logging out via {} (score {:.2f})".format(button, score))
        self.driver.click_at(center)
        time.sleep(self.config.get("permata_logout_process_wait", 3.0))
