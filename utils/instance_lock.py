"""Cross-platform single-instance file lock.

Windows lets two servers bind the same port when SO_REUSEADDR is set, which
left stale ``api.py``/``app.py`` processes answering (or failing to answer)
requests. An exclusive OS lock on a small file makes the second process exit
instead of running a duplicate.
"""

import os


def acquire_instance_lock(path):
    """Take an exclusive OS lock; returns an open handle or ``None``.

    Keep the returned handle open for the lifetime of the process. The OS
    releases it automatically on exit, including a crash or hard kill.
    """
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        handle = open(path, "a+")
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle
