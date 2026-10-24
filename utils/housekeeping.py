"""Routine cleanup of files the scraper leaves behind.

Each scrape runs Chrome with a fresh ``tempfile.mkdtemp()`` profile that
:meth:`bank.base.ChromeDriver.close` deletes. A hard kill or a crash can skip
that cleanup, leaving a ``bca_bot_profile_*`` directory (Chrome cache included,
~19 MB) in the system temp directory. :func:`cleanup_stale_profiles` sweeps
those up at scraper startup so they cannot accumulate over months.
"""

import os
import shutil
import tempfile
import time

from utils.output import log

PROFILE_PREFIX = "bca_bot_profile_"
# Only profiles older than this are removed, so an in-flight scrape (even one
# started by another instance on the same machine) is never disturbed.
STALE_PROFILE_AGE = 6 * 60 * 60


def cleanup_stale_profiles(max_age_seconds=STALE_PROFILE_AGE):
    """Delete abandoned ``bca_bot_profile_*`` dirs; returns how many."""
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    now = time.time()
    removed = 0
    for name in names:
        if not name.startswith(PROFILE_PREFIX):
            continue
        path = os.path.join(root, name)
        try:
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            if now - os.path.getmtime(path) < max_age_seconds:
                continue
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.isdir(path):
                removed += 1
        except OSError:
            continue
    if removed:
        log(
            "cleanup: removed {} stale Chrome profile(s) from {}".format(
                removed, root
            )
        )
    return removed
