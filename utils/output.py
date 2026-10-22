"""Output helpers: logging, label sanitization, and text file writing."""

import os
import re
import sys
import time

try:
    # Page titles and account text can contain characters outside the console
    # code page; logging them must never abort the run.
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

_log_file = None


def configure_log_file(path):
    """Tee subsequent log() output to *path* (appended, flushed each line).

    Passing a falsey value disables file logging. The parent directory is
    created if needed.
    """
    global _log_file
    if not path:
        _log_file = None
        return
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    _log_file = path


def log(msg):
    """Print a timestamped message, flushing immediately; tee to file if set."""
    stamp = time.strftime("%H:%M:%S")
    line = "[{}] {}".format(stamp, msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    if _log_file:
        try:
            with open(_log_file, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
                f.flush()
        except OSError:
            pass


def sanitize_label(label):
    """Make *label* safe to use as a filename stem."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label)).strip("._-")
    return safe or "account"


def account_output_path(label, output_dir="output"):
    """Return the output .txt path for *label*."""
    return os.path.join(output_dir, "{}.txt".format(sanitize_label(label)))


def write_account_txt(label, text, output_dir="output"):
    """Write captured statement text to output/{label}.txt (UTF-8, no BOM)."""
    os.makedirs(output_dir, exist_ok=True)
    path = account_output_path(label, output_dir)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    log("wrote {} ({} chars)".format(path, len(text)))
    return path
