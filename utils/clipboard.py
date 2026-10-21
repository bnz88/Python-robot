"""Clipboard read helper with empty retry."""

import time

import pyperclip


def get_clipboard_text(retries=2, delay=0.5):
    """Return the current clipboard text, retrying on empty reads."""
    for attempt in range(retries):
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if text and text.strip():
            return text
        if attempt < retries - 1:
            time.sleep(delay)
    return ""
