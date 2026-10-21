"""PERMATA captcha dataset helpers.

The labeled dataset lives in ``dataset/permata`` (override with
``permata_dataset_dir``): real captcha crops in ``images/`` and labels in
``labels.txt`` as ``<filename><TAB><text>`` (exact case, e.g. ``sf4H``). Blank
lines and lines starting with ``#`` are ignored. The same format is what
``dddd_trainer`` expects if a model is ever trained later.

Used by ``utils.captcha`` (optional production capture of solved captchas) and
by the offline tools in ``tools/``.
"""

import hashlib
import io
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_DATASET_DIR = os.path.join("dataset", "permata")
HEADER = (
    "# PERMATA captcha labeled dataset.\n"
    "# One sample per line: <filename><TAB><text>  (exact case, e.g. sf4H)\n"
    "# Files live in dataset/permata/images/. Lines starting with # are ignored.\n"
    "#\n"
    "# Example rows (replace with your own image files and labels, TAB-separated):\n"
    "# 0001.png\tsf4H\n"
    "# 0002.png\tRfGL\n"
    "# 0003.png\tnjb7\n"
    "# 0004.png\t9XCh\n"
)


def dataset_dir(config=None):
    """Absolute dataset directory (``permata_dataset_dir`` or the default)."""
    directory = DEFAULT_DATASET_DIR
    if config:
        directory = config.get("permata_dataset_dir") or directory
    if not os.path.isabs(directory):
        directory = os.path.join(BASE_DIR, directory)
    return directory


def images_dir(config=None):
    return os.path.join(dataset_dir(config), "images")


def labels_path(config=None):
    return os.path.join(dataset_dir(config), "labels.txt")


def misses_dir(config=None):
    return os.path.join(dataset_dir(config), "misses")


def ensure_dirs(config=None):
    os.makedirs(images_dir(config), exist_ok=True)


def parse_labels(text):
    """Parse ``filename<TAB>text`` lines into a list of ``(filename, text)``."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            name, label = line.split("\t", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            name, label = parts
        name = name.strip()
        label = label.strip()
        if name and label:
            rows.append((name, label))
    return rows


def load_labels(path=None, config=None):
    """Read the label rows; returns ``[]`` when the file does not exist."""
    path = path or labels_path(config)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return parse_labels(handle.read())


def iter_samples(config=None, limit=None):
    """Yield ``(image_path, text)`` for labeled samples whose image exists."""
    directory = images_dir(config)
    count = 0
    for name, label in load_labels(config=config):
        path = name if os.path.isabs(name) else os.path.join(directory, name)
        if not os.path.exists(path):
            continue
        yield path, label
        count += 1
        if limit is not None and count >= limit:
            return


def save_sample(shot, config=None):
    """Save a captcha crop (PIL image) to ``images/``; returns its path.

    The name embeds the capture time and a content hash, so the same image is
    not stored twice. The crop is saved unlabeled; a successful login later
    confirms it via :func:`confirm_sample`.
    """
    ensure_dirs(config)
    buffer = io.BytesIO()
    shot.save(buffer, format="PNG")
    data = buffer.getvalue()
    digest = hashlib.sha1(data).hexdigest()[:12]
    name = "{}_{}.png".format(time.strftime("%Y%m%d_%H%M%S"), digest)
    path = os.path.join(images_dir(config), name)
    if not os.path.exists(path):
        with open(path, "wb") as handle:
            handle.write(data)
    return path


def _relocate_into_images(path, config=None):
    """Return a path inside ``images/`` (copying *path* there if needed)."""
    directory = images_dir(config)
    target = os.path.join(directory, os.path.basename(path))
    if os.path.abspath(path) == os.path.abspath(target):
        return target
    if os.path.exists(target):
        return target
    if not os.path.exists(path):
        return None
    ensure_dirs(config)
    with open(path, "rb") as src, open(target, "wb") as dst:
        dst.write(src.read())
    return target


def confirm_sample(path, text, config=None):
    """Record a captcha crop + its accepted text as a labeled sample.

    Called after a successful login (the submitted captcha was accepted), which
    yields a perfectly case-labeled sample. The crop is copied into ``images/``
    if needed and ``<filename><TAB><text>`` is appended to ``labels.txt`` once.
    Returns the label row ``(filename, text)`` or None when the crop is missing.
    """
    if not path or not text:
        return None
    relocated = _relocate_into_images(path, config)
    if not relocated:
        return None
    name = os.path.basename(relocated)
    labels = labels_path(config)
    existing = dict(load_labels(path=labels))
    if existing.get(name) == text:
        return (name, text)
    os.makedirs(os.path.dirname(labels), exist_ok=True)
    prefix = ""
    if not os.path.exists(labels) or os.path.getsize(labels) == 0:
        prefix = HEADER
    with open(labels, "a", encoding="utf-8") as handle:
        handle.write("{}{}\t{}\n".format(prefix, name, text))
    return (name, text)
