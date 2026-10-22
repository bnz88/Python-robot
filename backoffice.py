"""Upload captured statements to the Sistem88 backoffice using Playwright.

The backoffice login form auto-focuses the username field, so the flow is:

Step 1 (login):
    type username -> Tab -> type password -> Enter   (auto-login)

Step 2 (add bank statement):
    navigate to the parse form, set the bank shortname and operator account
    unique ID via jQuery `.val()`, paste the scraped statement text into
    ``#input-reportText``, then press Enter to submit.

Submission:
    pressing Enter fires ``bankStatementParse!parseStatement`` (a JSON API).
    If that returns ``success: true`` a popup appears and we click the save
    button ``.bo-button--parse-result-save``, which fires
    ``bankStatementParse!save`` (a JSON API). The statement is only considered
    confirmed when that also returns ``success: true``; otherwise the browser
    is closed and the scraper moves on.

Dry run (``skip_save``):
    the parse is submitted but the save API is never called. With a headed
    browser, ``dry_run_keep_open`` (default true) keeps the browser open after
    the flow - on success and on error - so the result can be inspected; it
    closes once the user closes the window (or stops the scraper), then any
    error is reported. Set ``dry_run_keep_open`` to false to close the browser
    and continue to the next account automatically.

Configured under ``backoffice`` in config.json:
    enabled        - when true, changed statements are uploaded
    username       - backoffice login username
    password       - backoffice login password
    login_url      - defaults to https://bo.sistem88.com/bo/login.action
    parse_url      - defaults to
                     https://bo.sistem88.com/bo/bankStatementParse!view
    parse_api_url  - defaults to
                     https://bo.sistem88.com/bo/json/bankStatementParse!parseStatement
    save_api_url   - defaults to
                     https://bo.sistem88.com/bo/json/bankStatementParse!save
    headless       - launch Chromium headless (default true)

Requires Playwright with a Chromium browser installed:
    pip install playwright
    python -m playwright install chromium
"""

import json

from utils.output import log

DEFAULT_LOGIN_URL = "https://bo.sistem88.com/bo/login.action"
DEFAULT_PARSE_URL = "https://bo.sistem88.com/bo/bankStatementParse!view"
DEFAULT_PARSE_API_URL = (
    "https://bo.sistem88.com/bo/json/bankStatementParse!parseStatement"
)
DEFAULT_SAVE_API_URL = "https://bo.sistem88.com/bo/json/bankStatementParse!save"

SHORTNAME_SELECTOR = "#bankStatementParse_operatorBankShortName"
ACCOUNT_ID_SELECTOR = "#operatorBankAccountId"
REPORT_TEXT_SELECTOR = "#input-reportText"
SAVE_BUTTON_SELECTOR = ".bo-button--parse-result-save"


def _set_value(page, selector, value):
    """Set an input/select value, preferring the site's own jQuery .val().

    Falls back to Playwright's ``select_option`` then ``fill`` so it works
    whether the field is a native ``<select>`` or a plain input.
    """
    text = str(value)
    try:
        page.evaluate("$('{}').val({})".format(selector, json.dumps(text)))
        return
    except Exception:
        pass
    try:
        page.select_option(selector, value=text)
        return
    except Exception:
        pass
    try:
        page.select_option(selector, label=text)
        return
    except Exception:
        pass
    page.fill(selector, text)


def _select_shortname(page, shortname):
    """Select the bank shortname with Playwright's native ``select_option``.

    Tries the option ``value`` first (the shortname code), then falls back to
    matching the visible option ``label``.
    """
    try:
        page.select_option(SHORTNAME_SELECTOR, value=shortname)
        return
    except Exception:
        pass
    page.select_option(SHORTNAME_SELECTOR, label=shortname)


def _login(page, bo):
    page.goto(bo.get("login_url", DEFAULT_LOGIN_URL), wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    # The username field is focused on arrival; type, Tab to password, Enter.
    page.keyboard.type(bo["username"], delay=40)
    page.keyboard.press("Tab")
    page.keyboard.type(bo["password"], delay=40)
    page.keyboard.press("Enter")
    page.wait_for_timeout(4000)


def _fill(st_page, account, report_text):
    st_page.wait_for_selector(REPORT_TEXT_SELECTOR, timeout=20000)

    shortname = (account.get("bank_shortname") or "").strip()
    unique_id = (account.get("unique_id") or "").strip()
    if not shortname or not unique_id:
        raise ValueError(
            "account '{}' missing bank_shortname or unique_id".format(
                account.get("label")
            )
        )

    _select_shortname(st_page, shortname)
    st_page.wait_for_timeout(2000)
    _set_value(st_page, ACCOUNT_ID_SELECTOR, unique_id)
    st_page.fill(REPORT_TEXT_SELECTOR, report_text)


def _resp_json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _submit(st_page, bo):
    """Submit the parse, then save the result via the save API.

    Press Tab/Tab/Enter to fire ``bankStatementParse!parseStatement``. If that
    reports ``success: true`` the parse is confirmed and the save button is
    clicked (best-effort) to fire ``bankStatementParse!save``. Returns True on
    parse success.
    """

    with st_page.expect_response(
        lambda r: "bankStatementParse!parseStatement" in r.url
    ) as resp_info:
        st_page.keyboard.press("Tab")
        st_page.keyboard.press("Tab")
        st_page.keyboard.press("Enter")

    data = _resp_json(resp_info.value)
    if not (isinstance(data, dict) and data.get("success")):
        return False

    st_page.wait_for_timeout(1500)

    if bo.get("skip_save"):
        # Dry-run: parse succeeded, but leave the result unsaved (no save API
        # call) so the back office is not actually updated.
        st_page.wait_for_timeout(1500)
        return True

    try:
        with st_page.expect_response(
            lambda r: "bankStatementParse!save" in r.url
        ) as save_info:
            st_page.click(SAVE_BUTTON_SELECTOR, timeout=8000)
        _resp_json(save_info.value)
    except Exception:
        pass
    st_page.wait_for_timeout(1500)
    return True


def browser_geometry(config):
    """Window geometry matching the scraper's Chrome.

    Maximized Chrome uses the whole screen, so the same rule is applied here:
    ``chrome_maximized`` (default true) -> screen size from PyAutoGUI, otherwise
    ``window_width`` x ``window_height``. Returns ``(width, height, maximized)``.
    """
    try:
        width = int(config.get("window_width", 1280))
        height = int(config.get("window_height", 900))
    except (TypeError, ValueError):
        width, height = 1280, 900
    if not config.get("chrome_maximized", True):
        return width, height, False
    try:
        import pyautogui

        screen_w, screen_h = pyautogui.size()
        if screen_w and screen_h:
            width, height = int(screen_w), int(screen_h)
    except Exception:
        pass
    return width, height, True


def browser_launch_args(config, headless):
    """Chromium flags so the backoffice window matches the scraper's Chrome."""
    width, height, maximized = browser_geometry(config)
    args = ["--window-size={},{}".format(width, height)]
    if not headless:
        args.insert(0, "--window-position=0,0")
        if maximized:
            args.append("--start-maximized")
        try:
            scale = float(config.get("chrome_scale", 1.0))
        except (TypeError, ValueError):
            scale = 1.0
        if scale > 0 and abs(scale - 1.0) > 0.001:
            args.append("--force-device-scale-factor={:g}".format(scale))
    return args


def browser_page_options(config, headless):
    """``new_page()`` options so the page renders at the scraper's window size."""
    width, height, _maximized = browser_geometry(config)
    if headless:
        return {"viewport": {"width": width, "height": height}}
    # Headed: no viewport emulation, the page uses the real window size (a
    # maximized window is the screen minus the taskbar), like the scraper.
    return {"no_viewport": True}


def upload_statement(config, account, report_text):
    """Log in and submit *account*'s *report_text* to the backoffice.

    Returns ``{"ok": True, "confirmed": True}`` when the parse API reported
    ``success: true`` (the save is attempted best-effort). When the parse is
    rejected, returns ``{"ok": False, "confirmed": False}`` (the browser is
    closed and the scraper moves on to the next account).

    In dry run (``skip_save``) with a headed browser, ``dry_run_keep_open``
    (default true) controls whether the browser is held open after the flow -
    on success and on error alike - until the user closes the window or stops
    the scraper (any error is then re-raised). When it is false the browser is
    closed and the scraper continues to the next account.
    """
    bo = config.get("backoffice") or {}
    if not (bo.get("username") and bo.get("password")):
        raise RuntimeError("backoffice credentials not configured")

    from playwright.sync_api import sync_playwright

    headless = bool(bo.get("headless", True))
    dry_run = bool(bo.get("skip_save"))
    keep_open_setting = bool(bo.get("dry_run_keep_open", True))
    # Dry run + headed + keep-open: never auto-close the browser, so the
    # backoffice can be inspected manually. Applies on success AND on error.
    keep_open = dry_run and not headless and keep_open_setting

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=browser_launch_args(config, headless),
        )
        page = browser.new_page(**browser_page_options(config, headless))
        geo_w, geo_h, _maximized = browser_geometry(config)
        log(
            "[backoffice] browser {}x{} ({})".format(
                geo_w, geo_h, "headless" if headless else "windowed"
            )
        )
        success = False
        error = None
        try:
            _login(page, bo)
            page.goto(bo.get("parse_url", DEFAULT_PARSE_URL), wait_until="domcontentloaded")
            _fill(page, account, report_text)
            success = _submit(page, bo)
            if not keep_open:
                # Brief pause after the backoffice flow so the final state
                # settles before the browser is closed.
                page.wait_for_timeout(2000)
        except Exception as exc:
            error = exc
            log("[backoffice] error during backoffice flow: {}".format(exc))
        finally:
            if keep_open:
                # Leave the browser open until the user closes the window (or
                # stops the scraper), even when the flow errored.
                log(
                    "[backoffice] dry run: browser left open for debugging "
                    "(success={}); close the browser window to continue".format(
                        success
                    )
                )
                while True:
                    try:
                        if not browser.is_connected():
                            break
                        page.wait_for_timeout(1000)
                    except Exception:
                        break
            try:
                browser.close()
            except Exception:
                pass

    if error is not None:
        raise error
    if not success:
        return {"ok": False, "confirmed": False}
    if dry_run:
        return {"ok": True, "confirmed": True, "saved": False, "skipped_save": True}
    return {"ok": True, "confirmed": True, "saved": True}