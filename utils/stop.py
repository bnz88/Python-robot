"""Cooperative stop request shared by the control panel and the scraper.

The panel starts the scraper in its own console, so it cannot deliver a
Ctrl+Break to it. It used to force-kill the process tree, which skipped the
scraper's cleanup and left the per-scrape Chrome profile (~19 MB) behind in
the system temp directory.

Now the panel only writes a small flag file next to ``status.json``. The
scraper polls it and exits through its normal ``finally`` path, so
``driver.close()`` still terminates Chrome and removes the profile.

``StopRequested`` derives from ``BaseException`` (like ``KeyboardInterrupt``)
so the broad ``except Exception`` handlers in the scrape flows cannot swallow
it, while ``finally`` blocks still run.
"""

import os
import threading

FLAG_NAME = "stop.request"
POLL_INTERVAL = 0.2

_event = threading.Event()
_flag_path = None
_watcher = None
_watcher_lock = threading.Lock()


class StopRequested(BaseException):
    """Raised inside the scraper when the operator asked it to stop."""


def stop_flag_path(config, base_dir=None):
    """Path of the stop flag file, resolved like the status file."""
    out_dir = config.get("output_dir", "output")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(base_dir or os.getcwd(), out_dir)
    return os.path.join(out_dir, FLAG_NAME)


def request_stop(config, base_dir=None):
    """Write the stop flag the scraper polls (called by the panel)."""
    path = stop_flag_path(config, base_dir)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return path


def clear_stop(config, base_dir=None):
    """Remove the stop flag (never raises)."""
    try:
        os.remove(stop_flag_path(config, base_dir))
    except OSError:
        pass


def _watch(path):
    while not _event.is_set():
        try:
            if os.path.isfile(path):
                _event.set()
                return
        except OSError:
            pass
        _event.wait(POLL_INTERVAL)


def start_watching(config, base_dir=None):
    """Start polling the stop flag; returns the watched path."""
    global _watcher, _flag_path
    with _watcher_lock:
        _event.clear()
        _flag_path = stop_flag_path(config, base_dir)
        if _watcher is None or not _watcher.is_alive():
            _watcher = threading.Thread(
                target=_watch,
                args=(_flag_path,),
                daemon=True,
                name="stop-watcher",
            )
            _watcher.start()
        return _flag_path


def should_stop():
    return _event.is_set()


def check():
    """Raise :class:`StopRequested` when a stop was requested."""
    if _event.is_set():
        raise StopRequested()


def sleep(seconds):
    """Sleep, but wake up early (raising StopRequested) on a stop request."""
    if _event.wait(seconds):
        raise StopRequested()
