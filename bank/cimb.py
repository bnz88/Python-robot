"""CIMB flow: image-gated login, direct statement URL, capture, image logout.

Steps (all waits/scales configurable via config.json "cimb_*"):
1. Launch Chrome to the login URL.
2. Wait for the login form image (`cimb_user_id_image`, default `user_id.JPG`).
3. Wait, click the user id input box image, type the username, Tab once, type
   the password, then Enter to authenticate.
4. Wait for the logged-in image (`cimb_logout_button`, default
   `cimb_logout_btn.JPG`, i.e. the logout button) to confirm the dashboard.
5. Navigate directly to the statement URL and wait for it to render.
6. Ctrl+A / Ctrl+C to capture the statement text (same as the other banks).
7. Log out via the logout button image, then continue to the backoffice.

When the login-form or logout-button image cannot be found the run is aborted
with ``ScrapeAborted``: main.py clears that account's cooldown, does not flag it
as scraped, and moves on to the next account.

Matching is scale-tolerant (see ``ChromeDriver.locate_image``) because the
reference images may have been captured at a different display scale; the scale
factors come from ``cimb_image_scales``.
"""

from bank.base import ChromeDriver, ScrapeAborted
from utils.output import log, write_account_txt
from utils.stop import sleep as stop_sleep


class CIMB:
    def __init__(self, config):
        self.config = config
        self.driver = ChromeDriver(config, "cimb")

    def run(self, account, capture_mode=False):
        login_url = self.config.get(
            "cimb_login_url", "https://www.cimbocto.co.id/login"
        )
        statement_url = self.config.get(
            "cimb_statement_url", "https://www.cimbocto.co.id/myaccount/casa/1"
        )

        self.driver.launch(login_url)

        if capture_mode:
            input(
                "Capture mode [cimb]: save assets/cimb/ reference images "
                "(user_id.JPG, cimb_logout_btn.JPG, ...) as needed, then press "
                "Enter to continue..."
            )
        else:
            self._wait_for_page(
                self.config.get("cimb_user_id_image", "user_id.JPG"),
                "login form",
            )

        self._login(account["username"], account["password"])

        if not capture_mode:
            self._wait_for_page(
                self.config.get("cimb_logout_button", "cimb_logout_btn.JPG"),
                "dashboard (logged in)",
            )
            logged_in_wait = self.config.get("cimb_logged_in_wait", 5.0)
            log(
                "[cimb] waiting {:.1f}s after login before the statement".format(
                    logged_in_wait
                )
            )
            stop_sleep(logged_in_wait)

        log("[cimb] opening the statement page: {}".format(statement_url))
        self.driver.goto_url(statement_url)
        statement_wait = self.config.get("cimb_statement_wait", 8.0)
        log(
            "[cimb] waiting {:.1f}s for the statement to render".format(
                statement_wait
            )
        )
        stop_sleep(statement_wait)

        text = self.driver.capture_statement_text(account["label"])
        if capture_mode:
            out_path = write_account_txt(
                account["label"], text, self.config["output_dir"]
            )
            log("[cimb] capture mode: wrote {}".format(out_path))

        if not capture_mode:
            try:
                self._logout()
            except Exception as exc:
                log("[cimb] logout failed: {}".format(exc))

        return text

    # ------------------------------------------------------------------ checks
    def _wait_for_page(self, image, page):
        """Wait for a page-check image; abort the account when it never shows.

        Raises ``ScrapeAborted`` so main.py stops this account without
        flagging it as scraped (cooldown cleared, next account continues).
        """
        timeout = self.config.get(
            "cimb_page_timeout", self.config.get("image_timeout", 15)
        )
        scales = self.config.get(
            "cimb_image_scales", [1.0, 0.8, 0.67, 0.5, 1.25, 1.5]
        )
        log(
            "[cimb] waiting up to {:.0f}s for the {} ({})".format(
                timeout, page, image
            )
        )
        center, score = self.driver.locate_image(
            image, timeout=timeout, scales=scales
        )
        if center is None:
            raise ScrapeAborted(
                "{} did not load (image not found: {}; best score {:.2f})".format(
                    page, image, score
                )
            )
        log("[cimb] {} loaded (score {:.2f})".format(page, score))

    def _click_image(self, image, what):
        """Locate *image* and click it, aborting the account when not found."""
        timeout = self.config.get(
            "cimb_page_timeout", self.config.get("image_timeout", 15)
        )
        scales = self.config.get(
            "cimb_image_scales", [1.0, 0.8, 0.67, 0.5, 1.25, 1.5]
        )
        center, score = self.driver.locate_image(
            image, timeout=timeout, scales=scales
        )
        if center is None:
            raise ScrapeAborted(
                "{} not found (image: {}; best score {:.2f})".format(
                    what, image, score
                )
            )
        log("[cimb] clicking {} ({}) score {:.2f}".format(what, image, score))
        self.driver.click_at(center)

    # ------------------------------------------------------------------- login
    def _login(self, username, password):
        user_id_image = self.config.get("cimb_user_id_image", "user_id.JPG")
        login_wait = self.config.get("cimb_login_wait", 5.0)
        log(
            "[cimb] waiting {:.1f}s for the login form, then clicking the "
            "user id input".format(login_wait)
        )
        stop_sleep(login_wait)
        self._click_image(user_id_image, "user id input box")
        self.driver.type_text(username)
        self.driver.tab(1)
        self.driver.type_text(password)
        submit_wait = self.config.get("cimb_submit_wait", 1.0)
        stop_sleep(submit_wait)
        self.driver.press_enter()
        self.driver.handle_challenge()

    # ------------------------------------------------------------------ logout
    def _logout(self):
        logout_button = self.config.get(
            "cimb_logout_button", "cimb_logout_btn.JPG"
        )
        logout_wait = self.config.get("cimb_logout_wait", 5.0)
        log("[cimb] waiting {:.1f}s before logging out".format(logout_wait))
        stop_sleep(logout_wait)
        scales = self.config.get(
            "cimb_image_scales", [1.0, 0.8, 0.67, 0.5, 1.25, 1.5]
        )
        timeout = self.config.get(
            "cimb_page_timeout", self.config.get("image_timeout", 15)
        )
        center, score = self.driver.locate_image(
            logout_button, timeout=timeout, scales=scales
        )
        self.driver.logout_image_found = center is not None
        if center is None:
            log(
                "[cimb] logout button not found on screen ({}; best score "
                "{:.2f})".format(logout_button, score)
            )
            return
        log(
            "[cimb] logging out via {} (score {:.2f})".format(
                logout_button, score
            )
        )
        self.driver.click_at(center)
        stop_sleep(self.config.get("delay_long", 2.5))
