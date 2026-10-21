"""myBCA flow: the login page auto-focuses the username field.

Sequence: wait for the form, type username, Tab once to the password field,
type password, Enter, wait for the dashboard, then open the statement URL.
After scraping, log out via the top-right logout button.
"""

import os
import time

from bank.base import ChromeDriver
from utils.output import log, write_account_txt


class MyBCA:
    def __init__(self, config):
        self.config = config
        self.driver = ChromeDriver(config, "mybca")

    def run(self, account, capture_mode=False):
        login_url = self.config.get(
            "mybca_login_url", "https://mybca.bca.co.id/auth/login"
        )
        statement_url = self.config.get(
            "mybca_statement_url", "https://mybca.bca.co.id/profile/statement"
        )

        self.driver.launch(login_url)

        if capture_mode:
            input(
                "Capture mode [mybca]: save assets/mybca/challenge.png if a "
                "challenge screen appears. Press Enter to continue..."
            )

        self._login(account["username"], account["password"])

        log("[mybca] navigating to statement page")
        self.driver.goto_url(statement_url)

        statement_wait = self.config.get("mybca_statement_wait", 10.0)
        log("[mybca] waiting {:.1f}s for the statement to generate".format(statement_wait))
        time.sleep(statement_wait)

        if capture_mode:
            input(
                "Capture mode [mybca]: at statement page. Save "
                "assets/mybca/logout_button.png (top-right) if you want image-based "
                "logout, then press Enter to capture the text..."
            )

        text = self.driver.capture_statement_text(account["label"])
        if capture_mode:
            out_path = write_account_txt(
                account["label"], text, self.config["output_dir"]
            )
            log("[mybca] capture mode: wrote {}".format(out_path))

        if not capture_mode:
            try:
                self._logout()
            except Exception as exc:
                log("[mybca] logout failed: {}".format(exc))

        return text

    def _login(self, username, password):
        """Username is focused on load: type it, Tab once, type password, Enter."""
        self.driver.focus()
        form_wait = self.config.get("mybca_login_wait", 3.0)
        log("[mybca] waiting {:.1f}s for the login form".format(form_wait))
        time.sleep(form_wait)
        self.driver.type_text(username)
        self.driver.tab(1)
        self.driver.type_text(password)
        self.driver.press_enter()
        dashboard_wait = self.config.get("mybca_dashboard_wait", 5.0)
        log("[mybca] waiting {:.1f}s for the dashboard".format(dashboard_wait))
        time.sleep(dashboard_wait)
        self.driver.handle_challenge()

    def _logout(self):
        """Click the logout button at the top-right corner, then confirm if needed."""
        logout_wait = self.config.get("mybca_logout_wait", 2.0)
        log("[mybca] waiting {:.1f}s before logout".format(logout_wait))
        time.sleep(logout_wait)
        logout_img = self.driver.asset_path("logout_button.png")
        self.driver.logout_image_found = os.path.exists(logout_img)
        if os.path.exists(logout_img):
            log("[mybca] clicking logout button image")
            found = self.driver.click_image("logout_button.png")
            self.driver.logout_image_found = bool(found)
            if not found:
                log("[mybca] logout button not found on screen")
                return
        else:
            w = self.config["window_width"]
            x = self.config.get("mybca_logout_x")
            y = self.config.get("mybca_logout_y")
            x = (w - 40) if x is None else x
            y = 110 if y is None else y
            log("[mybca] clicking logout at top-right ({}, {})".format(x, y))
            self.driver.click_point(x, y)
        time.sleep(self.config["delay_long"])

        if os.path.exists(self.driver.asset_path("logout_confirm.png")):
            log("[mybca] confirming logout")
            self.driver.click_image("logout_confirm.png")
            time.sleep(self.config["delay_long"])

        process_wait = self.config.get("mybca_logout_process_wait", 3.0)
        log("[mybca] waiting {:.1f}s for logout to complete".format(process_wait))
        time.sleep(process_wait)

        log("[mybca] logged out")
