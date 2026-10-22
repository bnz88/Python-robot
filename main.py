"""BCA OS-level PyAutoGUI statement scraper entry point.

Usage:
    python main.py                  # run all accounts in accounts.json
    python main.py --account mybca    # run only mybca accounts
    python main.py --account klikbca
    python main.py --account cimb
    python main.py --account permata
    python main.py --capture        # pause to capture reference images
"""

import argparse
import json
import os
import tempfile
import threading
import time
import traceback

import pyautogui

from bank.base import ScrapeAborted
from bank.cimb import CIMB
from bank.klikbca import KlikBCA
from bank.mybca import MyBCA
from bank.permata import Permata
from utils.output import (
    account_output_path,
    configure_log_file,
    log,
    write_account_txt,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "accounts.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit("config.json not found at {}".format(CONFIG_PATH))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_accounts():
    if not os.path.exists(ACCOUNTS_PATH):
        raise SystemExit("accounts.json not found at {}".format(ACCOUNTS_PATH))
    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_accounts(accounts):
    if not isinstance(accounts, list) or not accounts:
        raise SystemExit("accounts.json must be a non-empty list")
    labels = set()
    for acc in accounts:
        bank = acc.get("bank")
        if bank not in ("klikbca", "mybca", "cimb", "permata"):
            raise SystemExit(
                "unknown bank: {!r} (must be 'klikbca', 'mybca', 'cimb' or "
                "'permata')".format(bank)
            )
        for key in ("username", "password", "label"):
            if not acc.get(key):
                raise SystemExit("account missing {!r} field".format(key))
        if acc["label"] in labels:
            raise SystemExit("duplicate label: {!r}".format(acc["label"]))
        labels.add(acc["label"])
        if "enabled" in acc and not isinstance(acc["enabled"], bool):
            raise SystemExit(
                "account {!r}: 'enabled' must be a boolean".format(acc["label"])
            )


def reload_enabled_accounts(bank=None):
    """Load accounts.json fresh and keep only enabled accounts (and bank filter)."""
    accounts = load_accounts()
    validate_accounts(accounts)
    if bank:
        accounts = [a for a in accounts if a["bank"] == bank]
    return [a for a in accounts if a.get("enabled", True)]


def make_runner(bank, config):
    if bank == "klikbca":
        return KlikBCA(config)
    if bank == "mybca":
        return MyBCA(config)
    if bank == "cimb":
        return CIMB(config)
    if bank == "permata":
        return Permata(config)
    raise ValueError("unknown bank: {!r}".format(bank))


def run_capture(config, accounts):
    seen = []
    for acc in accounts:
        if acc["bank"] not in seen:
            seen.append(acc["bank"])
    for bank in seen:
        account = next(a for a in accounts if a["bank"] == bank)
        runner = make_runner(bank, config)
        try:
            runner.run(account, capture_mode=True)
        finally:
            runner.driver.close()


def last_scrape_age(config, label):
    """Seconds since *label*'s output file was last written, or None if absent."""
    path = account_output_path(label, config.get("output_dir", "output"))
    if not os.path.isfile(path):
        return None
    return time.time() - os.path.getmtime(path)


def is_eligible(config, account):
    """True when the account has no output yet or its cooldown has elapsed."""
    age = last_scrape_age(config, account["label"])
    return age is None or age >= config.get("account_cooldown_seconds", 180)


def find_next_account(config, accounts, start=0, skip=None):
    """Return (index, wait_seconds) for the next account allowed to scrape.

    An account is eligible when its output file is missing or older than
    ``account_cooldown_seconds``. Labels in *skip* are passed over for this
    pass: they stay eligible (not flagged as scraped) but are not retried
    until no other account has work. The scan starts at *start* and wraps
    around, so after a run that did not advance an account's cooldown the
    loop moves on to the following account instead of re-picking the same
    one. When none are eligible, index is None and wait_seconds is the time
    until the earliest non-skipped account becomes eligible.
    """
    skip = skip or set()
    count = len(accounts)
    cooldown = config.get("account_cooldown_seconds", 180)
    remaining = []
    for offset in range(count):
        index = (start + offset) % count
        account = accounts[index]
        if account.get("label") in skip:
            continue
        age = last_scrape_age(config, account["label"])
        if age is None:
            return index, 0.0
        if age >= cooldown:
            return index, 0.0
        remaining.append(cooldown - age)
    if not remaining:
        return None, 0.0
    return None, min(remaining)


def next_eligible_label(config, accounts, index):
    """Label of the next eligible account after *index* (wrapping), or None."""
    count = len(accounts)
    for offset in range(1, count + 1):
        account = accounts[(index + offset) % count]
        if is_eligible(config, account):
            return account["label"]
    return None


def soonest_account(config, accounts):
    """Label of the account that becomes eligible soonest (None if empty)."""
    best_label = None
    best_remaining = None
    cooldown = config.get("account_cooldown_seconds", 180)
    for account in accounts:
        age = last_scrape_age(config, account["label"])
        if age is None:
            return account["label"]
        remaining = cooldown - age
        if best_remaining is None or remaining < best_remaining:
            best_remaining = remaining
            best_label = account["label"]
    return best_label


def reset_account_cooldowns(config, accounts):
    """Refresh per-account cooldowns at startup so every account is eligible.

    Each existing output file's mtime is pushed far enough into the past that
    ``is_eligible``/``find_next_account`` treat every account as ready
    immediately after the script starts.
    """
    cooldown = config.get("account_cooldown_seconds", 180)
    stamp = time.time() - cooldown - 1
    output_dir = config.get("output_dir", "output")
    touched = 0
    for account in accounts:
        path = account_output_path(account["label"], output_dir)
        if os.path.isfile(path):
            try:
                os.utime(path, (stamp, stamp))
                touched += 1
            except OSError:
                pass
    log(
        "per-account cooldown refreshed ({}/{} account files)".format(
            touched, len(accounts)
        )
    )


def live_interval_ms(config):
    """Capture interval in milliseconds.

    ``live_interval_ms`` is the millisecond setting (default 1000). The older
    ``live_interval`` in seconds is still honoured when the ms key is absent, so
    existing config files keep working. The result is clamped to 100 ms so a
    typo cannot peg the CPU with screenshots.
    """
    raw = config.get("live_interval_ms")
    if raw is None:
        try:
            raw = float(config.get("live_interval", 1.0)) * 1000.0
        except (TypeError, ValueError):
            raw = 1000.0
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 1000
    return max(100, value)


def start_live_capture(config):
    """Start a daemon thread that keeps ``output/live/frame.jpg`` up to date.

    Captures the desktop every ``live_interval_ms`` milliseconds (default 1000,
    minimum 100) while the scraper runs, so the control panel can show a
    per-robot live image. ``live_interval`` in seconds is used as a fallback.
    The frame is written atomically through a fixed temp file, so the folder
    never accumulates files and the API never serves a half-written image.
    Disabled when ``live_capture`` is false.
    """
    if not config.get("live_capture", True):
        return None
    interval_ms = live_interval_ms(config)
    interval = interval_ms / 1000.0

    out_dir = config.get("output_dir", "output")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(BASE_DIR, out_dir)
    live_dir = os.path.join(out_dir, "live")
    target = os.path.join(live_dir, "frame.jpg")
    tmp_path = os.path.join(live_dir, "frame.jpg.tmp")
    try:
        os.makedirs(live_dir, exist_ok=True)
    except OSError as exc:
        log("live capture disabled: cannot create {}: {}".format(live_dir, exc))
        return None

    stop = threading.Event()
    state = {"warned": False}

    def _run():
        while not stop.is_set():
            try:
                image = pyautogui.screenshot()
                image.save(tmp_path, "JPEG", quality=60)
                os.replace(tmp_path, target)
            except Exception as exc:
                if not state["warned"]:
                    state["warned"] = True
                    log("live capture failed: {}".format(exc))
            stop.wait(interval)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    log("live capture started ({} ms interval -> {})".format(interval_ms, target))
    return thread


def clear_account_cooldown(config, label):
    """Drop *label*'s cooldown stamp so the account is eligible immediately.

    Used when a scrape ended without finding the logout button: the statement
    is assumed not to have been captured, so the freshly written output file
    must not keep the account waiting a full cooldown period before a retry.
    """
    path = account_output_path(label, config.get("output_dir", "output"))
    try:
        if os.path.isfile(path):
            cooldown = config.get("account_cooldown_seconds", 180)
            stamp = time.time() - cooldown - 1
            os.utime(path, (stamp, stamp))
            log("cooldown cleared for {}; eligible for retry".format(label))
    except OSError:
        pass


def status_path(config):
    out_dir = config.get("output_dir", "output")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(BASE_DIR, out_dir)
    return os.path.join(out_dir, "status.json")


def next_override_path(config):
    """Path of the one-time 'scrape this account next' override file."""
    return os.path.join(os.path.dirname(status_path(config)), "next.json")


def read_next_override(config):
    """Label of the one-time priority jump, or None when not set/readable."""
    path = next_override_path(config)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get("label") if isinstance(data, dict) else None


def clear_next_override(config):
    path = next_override_path(config)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def write_status(config, current, next_label):
    """Atomically record which account is running and which is next up."""
    path = status_path(config)
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".status-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"current": current, "next": next_label, "updated": time.time()},
                f,
            )
        os.replace(tmp_path, path)
    except OSError:
        pass


def output_text(config, label):
    """Read the current scraped text for *label* ("" if missing/unreadable)."""
    path = account_output_path(label, config.get("output_dir", "output"))
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def statements_equal(prev, new):
    """True when two scraped statements are the same statement.

    Whitespace and line-insignificance differences (common with clipboard
    captures) are ignored: each line is stripped and blank lines dropped
    before comparing, so a re-scrape of an unchanged statement is not treated
    as a change.
    """
    return _normalize_statement(prev) == _normalize_statement(new)


def _normalize_statement(text):
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _count_rows_before_today(text):
    """Count transaction rows before today's KlikBCA block.

    Locates the first occurrence of today's ``DDMM/`` marker (e.g. ``1410/``)
    and counts the standalone ``CR``/``DB`` mutation-indicator lines before it.
    Each transaction row ends with exactly one such line, so the sum is the
    number of rows preceding today's block. When no today marker is present the
    whole text is counted.
    """
    now = time.localtime()
    today = "{:02d}{:02d}/".format(now.tm_mday, now.tm_mon)
    idx = text.find(today)
    if idx != -1:
        text = text[:idx]

    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "CR" or stripped == "DB":
            count += 1
    return count


def _positive_int(setting):
    """Return *setting* as a positive int, else 0 (falsy means 'no override')."""
    if not setting:
        return 0
    try:
        value = int(setting)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _omitted_row_count(config, account, text):
    """Resolve the ``x N`` omitted-row count for *account*, or 0 for none.

    Precedence: the account's own ``omitted_rows`` value when it is a positive
    number; otherwise the per-bank ``<bank>_omitted_rows`` setting; otherwise the
    bank's own detection logic. KlikBCA counts the ``CR``/``DB`` rows before
    today's block; myBCA has no detection logic, so it yields 0.
    """
    bank = account.get("bank") or ""
    value = _positive_int(account.get("omitted_rows"))
    if value:
        return value
    value = _positive_int(config.get(bank + "_omitted_rows"))
    if value:
        return value
    if bank == "klikbca":
        return _count_rows_before_today(text)
    return 0


def backoffice_report_text(config, account, text):
    """Text to paste into the backoffice for *account*.

    Appends one line break plus ``x <N>`` (the number of omitted rows) when a
    non-zero count is resolved. The count comes from the per-bank
    ``<bank>_omitted_rows`` setting when set to a positive number, otherwise
    from the bank's own detection logic. This extra line is only for the
    backoffice paste and is never written to the account's .txt file.
    """
    if not text:
        return text
    count = _omitted_row_count(config, account, text)
    if count:
        return text.rstrip("\r\n") + "\nx {}".format(count)
    return text


_missing_backoffice_fields = set()


def upload_to_backoffice(config, account, report_text):
    """Upload *report_text* to the backoffice when a statement changed.

    Returns ``"saved"`` when the backoffice accepted the statement (parse
    confirmed; in dry-run mode when parsing succeeded), ``"skipped"`` when no
    backoffice process ran (disabled, missing fields/credentials), and
    ``"failed"`` otherwise. Only a ``"saved"`` outcome lets the caller write
    the account's .txt file.
    """
    bo = config.get("backoffice") or {}
    if not bo.get("enabled"):
        return "skipped"
    label = account["label"]
    if not (account.get("unique_id") and account.get("bank_shortname")):
        if label not in _missing_backoffice_fields:
            _missing_backoffice_fields.add(label)
            log(
                "[backoffice] account {} missing unique_id/bank_shortname; "
                "upload skipped".format(label)
            )
        return "skipped"
    if not (bo.get("username") and bo.get("password")):
        log(
            "[backoffice] credentials not configured; skipping upload for {}".format(
                label
            )
        )
        return "skipped"
    try:
        from backoffice import upload_statement

        res = upload_statement(config, account, report_text) or {}
        if res.get("skipped_save"):
            _missing_backoffice_fields.discard(label)
            log(
                "[backoffice] dry-run (skip_save): parse success for {}; "
                "save NOT submitted".format(label)
            )
            return "saved"
        if res.get("confirmed"):
            _missing_backoffice_fields.discard(label)
            log("[backoffice] uploaded changed statement for {}".format(label))
            return "saved"
        log(
            "[backoffice] submit not confirmed for {}; "
            "please check the backoffice".format(label)
        )
        return "failed"
    except Exception as exc:
        log("[backoffice] upload failed for {}: {}".format(label, exc))
        return "failed"


def save_account_text(config, label, text):
    """Write the captured statement *text* to the account's output file."""
    return write_account_txt(label, text, config.get("output_dir", "output"))


def touch_output(config, label):
    """Bump the output file's mtime (cooldown) without rewriting its content."""
    path = account_output_path(label, config.get("output_dir", "output"))
    try:
        if os.path.isfile(path):
            os.utime(path, None)
    except OSError:
        pass


def process_scraped_account(config, account, result, prev_text):
    """Handle one scrape outcome: upload, then save only on success.

    The account's .txt file is never written before the backoffice process:
    it is saved only when the upload is accepted (or when the backoffice is
    disabled/otherwise skipped, or the statement is unchanged). A failed
    upload/submit leaves the file untouched, clears the cooldown and returns
    ``"not_captured"`` so the account is passed over this pass and the loop
    continues to the next account (no immediate retry). Returns an outcome
    string; ``"not_captured"`` means the account produced no statement (page
    check aborted, logout button not found, or backoffice upload/submit
    failed), so it was left un-flagged (cooldown cleared) and must be passed
    over this pass.
    """
    label = account["label"]
    status = result.get("status") if result else None
    logout_ok = result.get("logout_ok") if result else None
    new_text = result.get("text") if result else None
    if status == "aborted":
        log(
            "[scraper] {} stopped before capture ({}); statement not saved and "
            "account not flagged as scraped; cooldown cleared, moving on to "
            "the next account".format(
                label, (result.get("reason") or "page check failed")
            )
        )
        clear_account_cooldown(config, label)
        return "not_captured"
    if logout_ok is False:
        log(
            "[backoffice] logout button not found for {}; statement not "
            "saved and account not flagged as scraped; cooldown cleared, "
            "moving on to the next account".format(label)
        )
        clear_account_cooldown(config, label)
        return "not_captured"
    if not new_text:
        return "no_text"
    omitted = _omitted_row_count(config, account, new_text)
    if omitted >= 1 and account.get("bank") in ("klikbca", "mybca"):
        log(
            "[{}] {} rows omitted from the {} statement (sent to backoffice as "
            "'x {}')".format(account.get("bank"), omitted, label, omitted)
        )
    if statements_equal(prev_text, new_text):
        log("[backoffice] statement unchanged for {}; skipping upload".format(label))
        touch_output(config, label)
        return "unchanged"
    outcome = upload_to_backoffice(config, account, backoffice_report_text(config, account, new_text))
    if outcome == "saved":
        path = save_account_text(config, label, new_text)
        log("[backoffice] statement saved after upload for {} -> {}".format(label, path))
        return "saved"
    if outcome == "failed":
        log(
            "[backoffice] upload/submit not successful for {}; statement not "
            "saved; cooldown cleared, moving on to the next account".format(label)
        )
        clear_account_cooldown(config, label)
        return "not_captured"
    save_account_text(config, label, new_text)
    return "skipped_upload"


def scrape_account(config, account):
    """Open a fresh browser, scrape one account, close the browser."""
    label = account["label"]
    bank = account["bank"]
    runner = make_runner(bank, config)
    try:
        text = runner.run(account)
        logout_ok = getattr(getattr(runner, "driver", None), "logout_image_found", None)
        log("OK  {} captured {} chars".format(label, len(text or "")))
        return {
            "label": label,
            "bank": bank,
            "status": "ok",
            "text": text,
            "logout_ok": logout_ok,
        }
    except ScrapeAborted as exc:
        try:
            runner.driver.screenshot("{}_aborted.png".format(label))
        except Exception:
            pass
        log("ABORT {}: {}".format(label, exc))
        return {
            "label": label,
            "bank": bank,
            "status": "aborted",
            "reason": str(exc),
            "text": None,
        }
    except Exception as exc:
        try:
            runner.driver.screenshot("{}_error.png".format(label))
        except Exception:
            pass
        log("FAIL {}: {}".format(label, exc))
        traceback.print_exc()
        return {"label": label, "bank": bank, "status": "failed", "text": None}
    finally:
        log("[{}] closing browser".format(label))
        try:
            runner.driver.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="BCA statement scraper (PyAutoGUI)")
    parser.add_argument(
        "--capture", action="store_true", help="pause to capture reference images"
    )
    parser.add_argument(
        "--account", choices=["klikbca", "mybca", "cimb", "permata"], help="run only one bank"
    )
    parser.add_argument(
        "--proxy-ip", help="HTTP proxy IP/address for Chrome (no auth)"
    )
    parser.add_argument("--proxy-port", type=int, help="HTTP proxy port for Chrome")
    args = parser.parse_args()

    config = load_config()

    log_file = config.get("log_file")
    if log_file and not os.path.isabs(log_file):
        log_file = os.path.join(BASE_DIR, log_file)
    if log_file:
        configure_log_file(log_file)

    start_live_capture(config)

    accounts = load_accounts()
    validate_accounts(accounts)

    if args.proxy_ip and args.proxy_port:
        config["proxy_ip"] = args.proxy_ip
        config["proxy_port"] = args.proxy_port
        log(
            "using proxy http://{}:{}".format(args.proxy_ip, args.proxy_port)
        )

    if args.account:
        accounts = [a for a in accounts if a["bank"] == args.account]
        if not accounts:
            raise SystemExit("no accounts configured for bank {!r}".format(args.account))

    reset_account_cooldowns(config, accounts)

    if args.capture:
        run_capture(config, accounts)
        return

    loop_forever = config.get("loop_forever", True)
    cooldown = config.get("account_cooldown_seconds", 180)
    bank_filter = args.account
    scan_start = 0
    skipped = set()
    log("per-account cooldown: {}s".format(cooldown))
    try:
        if not loop_forever:
            for account in reload_enabled_accounts(bank_filter):
                if is_eligible(config, account):
                    prev_text = output_text(config, account["label"])
                    result = scrape_account(config, account)
                    process_scraped_account(config, account, result, prev_text)
            return

        while True:
            try:
                accounts = reload_enabled_accounts(bank_filter)
            except SystemExit as exc:
                write_status(config, None, None)
                log("accounts reload failed: {}; waiting 30s".format(exc))
                time.sleep(30.0)
                continue

            if not accounts:
                write_status(config, None, None)
                log("no enabled accounts to scrape; waiting 30s for a change")
                time.sleep(30.0)
                continue

            index = None
            wait = 0.0
            override_label = read_next_override(config)
            if override_label:
                found = next(
                    (
                        i
                        for i, a in enumerate(accounts)
                        if a.get("label") == override_label and a.get("enabled", True)
                    ),
                    None,
                )
                clear_next_override(config)
                if found is not None:
                    index = found
                    log(
                        "one-time priority jump: scraping {} next".format(override_label)
                    )
            if index is None:
                index, wait = find_next_account(
                    config, accounts, scan_start % len(accounts), skipped
                )
            if index is None:
                # Nothing non-skipped is scrape-ready right now. Wait for the
                # soonest healthy account, then start a fresh pass so any
                # account passed over for a missing logout button (cooldown
                # cleared, not flagged as scraped) is retried.
                healthy = [
                    a for a in accounts if a.get("label") not in skipped
                ]
                if wait <= 0 and skipped:
                    # Only cleared-cooldown failed accounts are left: back off
                    # for one cooldown period instead of retrying in a hot loop.
                    wait = cooldown
                upcoming = soonest_account(config, healthy) if healthy else None
                write_status(config, None, upcoming)
                log(
                    "all accounts within cooldown; waiting {:.1f}s; next up: {}".format(
                        wait, upcoming
                    )
                )
                time.sleep(wait)
                if skipped:
                    skipped.clear()
                    scan_start = 0
                continue

            current = accounts[index]["label"]
            bank = accounts[index]["bank"]
            upcoming = next_eligible_label(config, accounts, index)
            write_status(config, current, upcoming)
            log("")
            log("[{}] {}".format(bank, current))
            log("scraping {} (next: {})".format(current, upcoming))
            prev_text = output_text(config, current)
            result = scrape_account(config, accounts[index])
            outcome = process_scraped_account(config, accounts[index], result, prev_text)
            if outcome == "not_captured":
                skipped.add(current)
            scan_start = index + 1
            write_status(config, None, next_eligible_label(config, accounts, index))
            log("")

            between = config.get("between_accounts_wait", 5.0)
            log("waiting {:.1f}s before checking the next account".format(between))
            time.sleep(between)
    except KeyboardInterrupt:
        log("interrupted by user; exiting")


if __name__ == "__main__":
    main()
