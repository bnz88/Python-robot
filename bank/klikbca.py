"""KlikBCA flow: fixed-keystroke login and tab-based menu navigation.

Steps (all waits/tab counts configurable via config.json "klikbca_*"):
1. Wait for the landing page image before touching the login form.
2. Wait for the login form, type the username, Tab once, type the password,
   then Enter to authenticate.
3. Wait for the dashboard page image (the logout button).
4. Tab N times + Enter to open the main menu, wait.
5. Tab M times + Enter to open the bank statement page, wait.
6. Click the statement button image to generate the statement, wait.
7. Ctrl+A / Ctrl+C to capture the statement text (same as the other banks).
8. Log out via the logout button image, then continue to the backoffice like
   the other banks.

When a page-check image (landing page or dashboard) cannot be found the run is
aborted with ``ScrapeAborted``: main.py clears that account's cooldown, does
not flag it as scraped, and moves on to the next account.
"""

import os
import time

from bank.base import ChromeDriver, ScrapeAborted
from utils.output import log, write_account_txt


class KlikBCA:
    def __init__(self, config):
        self.config = config
        self.driver = ChromeDriver(config, "klikbca")

    def run(self, account, capture_mode=False):
        login_url = self.config.get(
            "klikbca_login_url", "https://ibank.klikbca.com/"
        )

        self.driver.launch(login_url)

        if capture_mode:
            input(
                "Capture mode [klikbca]: save assets/klikbca/statement_button.png "
                "and logout_button.JPG as needed, then press Enter to continue..."
            )
        else:
            self._wait_for_page(
                self.config.get("klikbca_landing_page", "landingpage.PNG"),
                "landing page",
            )

        self._login(account["username"], account["password"])

        if not capture_mode:
            self._wait_for_page(
                self.config.get("klikbca_logout_button", "logout_button.JPG"),
                "dashboard page",
            )

        self._open_statement(account["label"])

        text = self.driver.capture_statement_text(account["label"])
        if capture_mode:
            out_path = write_account_txt(
                account["label"], text, self.config["output_dir"]
            )
            log("[klikbca] capture mode: wrote {}".format(out_path))

        if not capture_mode:
            try:
                self._logout()
            except Exception as exc:
                log("[klikbca] logout failed: {}".format(exc))

        return text

    def _wait_for_page(self, image, page):
        """Wait for a page-check image; abort the account when it never shows.

        Raises ``ScrapeAborted`` so main.py stops this account without
        flagging it as scraped (cooldown cleared, next account continues).
        """
        timeout = self.config.get(
            "klikbca_page_timeout", self.config.get("image_timeout", 15)
        )
        log(
            "[klikbca] waiting up to {:.0f}s for the {} ({})".format(
                timeout, page, image
            )
        )
        if not self.driver.image_present(image, timeout=timeout):
            raise ScrapeAborted(
                "{} did not load (image not found: {})".format(page, image)
            )
        log("[klikbca] {} loaded".format(page))

    def _login(self, username, password):
        login_wait = self.config.get("klikbca_login_wait", 5.0)
        log("[klikbca] waiting {:.1f}s for the login form".format(login_wait))
        time.sleep(login_wait)
        self.driver.type_text(username)
        self.driver.tab(1)
        self.driver.type_text(password)
        self.driver.press_enter()
        dashboard_wait = self.config.get("klikbca_dashboard_wait", 7.0)
        log("[klikbca] waiting {:.1f}s to land on the bank dashboard".format(dashboard_wait))
        time.sleep(dashboard_wait)
        self.driver.handle_challenge()

    def _open_statement(self, label):
        menu_tabs = self.config.get("klikbca_menu_tabs", 10)
        menu_wait = self.config.get("klikbca_menu_wait", 2.0)
        log("[klikbca] opening the main menu (tab x{}, enter)".format(menu_tabs))
        self.driver.tab(menu_tabs)
        self.driver.press_enter()
        time.sleep(menu_wait)

        stmt_tabs = self.config.get("klikbca_stmt_tabs", 3)
        stmt_wait = self.config.get("klikbca_stmt_wait", 3.0)
        log(
            "[klikbca] going to the bank statement page (tab x{}, enter)".format(
                stmt_tabs
            )
        )
        self.driver.tab(stmt_tabs)
        self.driver.press_enter()
        time.sleep(stmt_wait)

        stmt_buttons = self.config.get(
            "klikbca_statement_buttons",
            ["statement_button.PNG", "statement2_button.PNG"],
        )
        button_timeout = self.config.get("klikbca_stmt_button_timeout", 5.0)
        scales = self.config.get(
            "klikbca_button_scales", [1.0, 0.8, 0.67, 0.5, 1.25, 1.5]
        )
        clicked = False
        best_score = 0.0
        for name in stmt_buttons:
            if not os.path.exists(self.driver.asset_path(name)):
                log("[klikbca] statement button image missing: {}".format(name))
                continue
            log("[klikbca] looking for statement button image: {}".format(name))
            center, score = self.driver.locate_image(
                name, timeout=button_timeout, scales=scales
            )
            best_score = max(best_score, score)
            if center is not None:
                log(
                    "[klikbca] clicking statement button image: {} "
                    "(score {:.2f})".format(name, score)
                )
                self.driver.click_at(center)
                clicked = True
                break
        if not clicked:
            fallback_tabs = self.config.get("klikbca_stmt_fallback_tabs", 14)
            log(
                "[klikbca] no statement button image found (best score "
                "{:.2f}); tab x{} + enter to generate".format(
                    best_score, fallback_tabs
                )
            )
            try:
                self.driver.screenshot("{}_stmt_button.png".format(label))
            except Exception:
                pass
            self.driver.tab(fallback_tabs)
            self.driver.press_enter()
        stmt_gen_wait = self.config.get("klikbca_statement_wait", 10.0)
        log(
            "[klikbca] waiting {:.1f}s for the statement to generate".format(
                stmt_gen_wait
            )
        )
        time.sleep(stmt_gen_wait)

    def _logout(self):
        logout_button = self.config.get(
            "klikbca_logout_button", "logout_button.JPG"
        )
        path = self.driver.asset_path(logout_button)
        self.driver.logout_image_found = os.path.exists(path)
        logout_wait = self.config.get("klikbca_logout_wait", 3.0)
        if not os.path.exists(path):
            log("[klikbca] logout button image missing: {}".format(logout_button))
            return
        log("[klikbca] logging out via {}".format(logout_button))
        found = self.driver.click_image(logout_button)
        self.driver.logout_image_found = bool(found)
        if not found:
            log("[klikbca] logout button not found on screen")
            return
        log("[klikbca] waiting {:.1f}s for logout to complete".format(logout_wait))
        time.sleep(logout_wait)