"""OCR helper for image captchas (used by the PERMATA bank flow).

Reads a captcha and returns its text. Primary engine is ``ddddocr`` (its beta
model), which handles noisy alphanumeric captchas well; ``pytesseract``
(Tesseract) is used as a fallback when ddddocr is not installed. Both are
imported lazily so banks that do not use captchas do not require them.

Two ways to find the captcha:

- ``read_captcha_near(driver, config)`` locates the captcha on screen by
  matching a reference image (``<prefix>_captcha_image``, default
  ``captcha.JPG``) and then OCRs the located region. Because the captcha text
  changes between captures, a single best match can land on the wrong place, so
  several distinct candidate locations are tried and the first region whose OCR
  yields a valid captcha is used. The match is blurred
  (``<prefix>_captcha_blur``) so it keys on the captcha's background pattern
  rather than the letters, is matched at ``<prefix>_captcha_confidence``
  (default 0.5), and the crops use the matched template size (scale-correct).
- ``read_captcha(config)`` OCRs a fixed screen region
  (``<prefix>_captcha_x/y/w/h``), used as a fallback when the reference image
  is not found.

Config keys (``<prefix>`` defaults to ``permata``):
    <prefix>_captcha_image        reference image name (default captcha.JPG)
    <prefix>_captcha_confidence   match threshold for the reference (default 0.5)
    <prefix>_captcha_padding      px added around the located captcha (default 0)
    <prefix>_captcha_blur         blur size for locating, odd px (default 15)
    <prefix>_captcha_candidates   max candidate locations to try (default 10)
    <prefix>_captcha_scales       match scales (default [1.0])
    <prefix>_captcha_x/y/w/h      fixed region fallback (ints)
    <prefix>_captcha_length       expected number of characters (default 4)
    <prefix>_captcha_charset      allowed characters, case-sensitive (default A-Za-z0-9)
    <prefix>_ocr_engine           'auto' (default) or 'ddddocr'/'tesseract'
    <prefix>_tesseract_cmd        path to the Tesseract executable (fallback)

Both readers return the cleaned string (exactly the expected length, case
preserved) or ``None`` when the captcha cannot be found or OCR cannot resolve
it, so the caller can treat ``None`` as a failure and refresh/retry. Note that
ddddocr's bundled model emits lowercase only (it does not distinguish case);
Tesseract preserves case.

Because the PERMATA captcha is case-sensitive but ddddocr cannot emit case,
``read_captcha_permata(shot, config)`` resolves the case without any model
training: it takes the letter sequence ddddocr is confident about and picks the
case from (1) the captcha's own font (``<prefix>_font_file``, built offline by
``tools/permata_font_id.py``) and/or (2) Tesseract case where its letters agree.
It never does worse than the plain engine consensus, which it falls back to.
``<prefix>_case_mode`` selects ``auto`` (default), ``font``, ``tesseract`` or
``baseline`` (skip case resolution). When ``<prefix>_capture_samples`` is on,
each located captcha crop is saved to ``dataset/permata/images`` for later
labeling (confirmed automatically after a successful login).
"""

import json
import os

from utils.output import log

DEFAULT_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
DEFAULT_FONT_FILE = os.path.join("assets", "permata", "font.json")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DDDDOCR = None
_DDDDOCR_FAILED = False
_DDDDOCR_OLD = None
_DDDDOCR_OLD_FAILED = False
_FONT_CACHE = {"key": None, "params": None}
_PILFONT_CACHE = {}
_GLYPH_TEMPLATE_CACHE = {}
_TESSERACT_WARNED = False


def _region(config, prefix):
    keys = [
        "{}_captcha_x".format(prefix),
        "{}_captcha_y".format(prefix),
        "{}_captcha_w".format(prefix),
        "{}_captcha_h".format(prefix),
    ]
    values = [config.get(k) for k in keys]
    if any(v is None for v in values):
        return None
    try:
        x, y, w, h = (int(v) for v in values)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _crop_region(center, size, padding):
    """Screen region (left, top, w, h) around *center* for a matched *size*."""
    width, height = size
    left = max(0, int(center[0] - width / 2) - padding)
    top = max(0, int(center[1] - height / 2) - padding)
    return (left, top, int(width) + 2 * padding, int(height) + 2 * padding)


def _safe(text):
    """Make OCR output safe to log on a non-UTF-8 console."""
    try:
        return text.encode("ascii", "replace").decode("ascii")
    except Exception:
        return "?"


def _clean(raw, charset, length):
    """Keep only allowed characters, preserving case (the captcha is mixed case)."""
    allowed = set(charset)
    cleaned = "".join(ch for ch in (raw or "") if ch in allowed)
    if not cleaned:
        return None
    if length and len(cleaned) != length:
        return None
    return cleaned


def _resolve_path(path):
    """Resolve a config path relative to the project root."""
    if not path:
        return None
    if os.path.isabs(path) or os.path.exists(path):
        return path
    return os.path.join(BASE_DIR, path)


def _letters(raw, charset, length):
    """Return the lowercased letter/digit sequence of the expected length."""
    allowed = set(charset)
    cleaned = "".join(ch for ch in (raw or "") if ch in allowed).lower()
    if length and len(cleaned) != length:
        return None
    return cleaned or None


def _get_ddddocr():
    """Return a cached ddddocr classifier (beta model), or None."""
    global _DDDDOCR, _DDDDOCR_FAILED
    if _DDDDOCR is not None or _DDDDOCR_FAILED:
        return _DDDDOCR
    try:
        import ddddocr
    except ImportError:
        _DDDDOCR_FAILED = True
        return None
    try:
        _DDDDOCR = ddddocr.DdddOcr(beta=True, show_ad=False)
    except TypeError:
        _DDDDOCR = ddddocr.DdddOcr(show_ad=False)
    except Exception as exc:
        log("[captcha] ddddocr init failed: {}".format(exc))
        _DDDDOCR_FAILED = True
        return None
    return _DDDDOCR


def _get_ddddocr_old():
    """Return a cached ddddocr classifier (old model), or None.

    A second opinion on the letters: the old model sometimes reads a glyph the
    beta model misses. Case resolution only needs the letters, so either model
    is fine as a source.
    """
    global _DDDDOCR_OLD, _DDDDOCR_OLD_FAILED
    if _DDDDOCR_OLD is not None or _DDDDOCR_OLD_FAILED:
        return _DDDDOCR_OLD
    try:
        import ddddocr
    except ImportError:
        _DDDDOCR_OLD_FAILED = True
        return None
    try:
        _DDDDOCR_OLD = ddddocr.DdddOcr(beta=False, show_ad=False)
    except Exception:
        _DDDDOCR_OLD_FAILED = True
        return None
    return _DDDDOCR_OLD


def _pytesseract_present():
    try:
        import pytesseract  # noqa: F401

        return True
    except ImportError:
        return False


def _preprocess(shot):
    """Upscale, grayscale and threshold the region to help Tesseract."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return shot
    array = np.array(shot)
    if array.ndim == 3:
        array = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    img = cv2.resize(array, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return 255 - img


def _run_ddddocr(ocr, shot):
    """Run one cached ddddocr classifier on *shot*, returning its raw text."""
    if ocr is None:
        return None
    try:
        import io

        buf = io.BytesIO()
        shot.save(buf, format="PNG")
        return ocr.classification(buf.getvalue())
    except Exception as exc:
        log("[captcha] ddddocr OCR failed: {}".format(exc))
        return None


def _ddddocr_read(shot):
    return _run_ddddocr(_get_ddddocr(), shot)


def _ddddocr_reads(shot):
    """Raw ddddocr reads from each available model, beta first, de-duplicated."""
    reads = []
    for ocr in (_get_ddddocr(), _get_ddddocr_old()):
        raw = _run_ddddocr(ocr, shot)
        if raw and raw not in reads:
            reads.append(raw)
    return reads


def _tesseract_read_raw(image, config, prefix, psm=7):
    """Run Tesseract on an already-prepared image at the given PSM mode."""
    global _TESSERACT_WARNED
    try:
        import pytesseract
    except ImportError:
        return None
    tesseract_cmd = config.get("{}_tesseract_cmd".format(prefix))
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    charset = config.get("{}_captcha_charset".format(prefix), DEFAULT_CHARSET)
    tess_config = "--psm {} -c tessedit_char_whitelist={}".format(psm, charset)
    try:
        return pytesseract.image_to_string(image, config=tess_config)
    except Exception as exc:
        if not _TESSERACT_WARNED:
            # The engine is usually simply not installed; warn once, not per call.
            log("[captcha] tesseract OCR failed: {}".format(exc))
            _TESSERACT_WARNED = True
        return None


def _tesseract_read(shot, config, prefix):
    return _tesseract_read_raw(_preprocess(shot), config, prefix, psm=7)


def _tesseract_variants(shot, config, prefix):
    """Ordered Tesseract reads at PSM 7, best preprocessing first.

    A single preprocessing choice can drop or merge glyphs, so a grayscale read
    and the shared ``_preprocess`` (upscaled Otsu) read are both taken; each is
    one subprocess spawn. The preprocessed read is tried first because it is the
    more accurate of the two on noisy captchas, and the grayscale read is kept
    as a second opinion.
    """
    prepared = []
    try:
        from PIL import Image

        inverted = _preprocess(shot)  # upscaled Otsu, glyphs white on black
        if isinstance(inverted, Image.Image):
            prepared.append(("otsu_inv", inverted))
        else:
            prepared.append(("otsu_inv", Image.fromarray(inverted)))
    except Exception:
        pass
    prepared.append(("gray", shot.convert("L")))

    reads = []
    for _, image in prepared:
        raw = _tesseract_read_raw(image, config, prefix, psm=7)
        if raw and raw.strip():
            reads.append(raw)
    return reads


def _tesseract_reads(shot, config, prefix, length, charset):
    """Cleaned, exact-length Tesseract reads, best preprocessing first, deduped."""
    out = []
    for raw in _tesseract_variants(shot, config, prefix):
        cleaned = _clean(raw, charset, length)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _load_font_params(config, prefix):
    """Load and cache the ``font.json`` produced by ``tools/permata_font_id.py``."""
    path = config.get("{}_font_file".format(prefix)) or DEFAULT_FONT_FILE
    path = _resolve_path(path)
    if not path or not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime)
    if _FONT_CACHE["key"] == key:
        return _FONT_CACHE["params"]
    params = None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            params = json.load(handle)
    except (OSError, ValueError) as exc:
        log("[captcha] cannot read font file {}: {}".format(path, exc))
    _FONT_CACHE["key"] = key
    _FONT_CACHE["params"] = params
    return params


def _pil_font(cf, font_path, size):
    """Load and cache a PIL font keyed by (path, size, mtime)."""
    try:
        mtime = os.path.getmtime(font_path)
    except OSError:
        mtime = None
    key = (font_path, size, mtime)
    font = _PILFONT_CACHE.get(key)
    if font is None:
        font = cf.load_pil_font(font_path, size)
        _PILFONT_CACHE[key] = font
    return font


def _glyph_template(cf, font, char, rotation):
    """Render and cache a character template keyed by (id(font), char, rotation)."""
    key = (id(font), char, rotation)
    template = _GLYPH_TEMPLATE_CACHE.get(key)
    if template is None:
        template = cf.render_glyph(font, char, rotation)
        _GLYPH_TEMPLATE_CACHE[key] = template
    return template


def _font_template_case(shot, letters, config, prefix):
    """Resolve each glyph's case by matching it against the captcha font.

    Requires ``font.json`` (font path + size + rotation). The crop is segmented
    into glyphs; for every alphabetic position the captured glyph is compared
    against the same character rendered in both cases and the better match wins.
    The PIL font and the rendered templates are cached, so repeated captchas on
    the same font do not re-parse or re-render. Returns ``(string, confidence)``
    where confidence is the mean case margin, or ``(None, 0.0)`` when the font
    or a clean segmentation is unavailable.
    """
    params = _load_font_params(config, prefix)
    if not params:
        return None, 0.0
    try:
        from utils import captcha_font as cf
    except ImportError as exc:
        log("[captcha] font primitives unavailable: {}".format(exc))
        return None, 0.0

    font_path = cf.resolve_font(params.get("font"))
    if not font_path:
        return None, 0.0

    glyphs = cf.segment_label(cf.to_gray(shot), letters)
    if not glyphs:
        return None, 0.0

    size = int(params.get("size") or 40)
    rotation = float(params.get("rotation") or 0.0)
    try:
        font = _pil_font(cf, font_path, size)
    except Exception as exc:
        log("[captcha] cannot load font {}: {}".format(font_path, exc))
        return None, 0.0

    out = list(letters)
    margins = []
    for index, char in enumerate(letters):
        if not char.isalpha():
            continue
        upper = cf.glyph_similarity(
            glyphs[index], _glyph_template(cf, font, char.upper(), rotation)
        )
        lower = cf.glyph_similarity(
            glyphs[index], _glyph_template(cf, font, char.lower(), rotation)
        )
        out[index] = char.upper() if upper >= lower else char.lower()
        margins.append(abs(upper - lower))
    confidence = sum(margins) / len(margins) if margins else 0.0
    return "".join(out), confidence


def read_captcha_permata(shot, config, prefix="permata"):
    """Solve a PERMATA captcha case-accurately, without any model training.

    Two OCR engines contribute and the more reliable read wins:

    * **Tesseract** reads the whole string (letters *and* case). On the real
      PERMATA captcha it is markedly more accurate than ddddocr, so its
      preprocessed read is the primary result;
    * **ddddocr** supplies a lowercase letter sequence that is used as the
      fallback and, when a font is known, as the base for font-based case.

    The captcha's own font (``<prefix>_font_file``, built by
    ``tools/permata_font_id.py``) is applied as a case refinement when its
    per-glyph margin reaches ``<prefix>_case_min_score``.

    ``<prefix>_case_mode`` selects the source: ``auto`` (default: font case if
    confident, else Tesseract, else ddddocr), ``font``, ``tesseract`` or
    ``baseline`` (skip case resolution entirely). Returns the cleaned string of
    the expected length, or None when nothing resolves it.
    """
    length = config.get("{}_captcha_length".format(prefix), 4)
    charset = config.get("{}_captcha_charset".format(prefix), DEFAULT_CHARSET)
    mode = (config.get("{}_case_mode".format(prefix)) or "auto").lower()

    if mode == "baseline":
        return _ocr_shot(shot, config, prefix, verbose=False)

    tess_reads = _tesseract_reads(shot, config, prefix, length, charset)
    tess_best = tess_reads[0] if tess_reads else None

    if mode == "tesseract":
        return tess_best or _ocr_shot(shot, config, prefix, verbose=False)

    dd_letters = None
    for raw in _ddddocr_reads(shot):
        candidate = _letters(raw, charset, length)
        if candidate:
            dd_letters = candidate
            break

    # Case-correct the letters we trust most: Tesseract's when it produced a
    # valid read (its letters are the more accurate ones here), else ddddocr's.
    base_letters = tess_best.lower() if tess_best else dd_letters
    if mode in ("auto", "font") and base_letters:
        font_candidate, font_confidence = _font_template_case(
            shot, base_letters, config, prefix
        )
        min_score = config.get("{}_case_min_score".format(prefix), 0.05)
        if font_candidate and font_confidence >= min_score:
            resolved = _clean(font_candidate, charset, length)
            if resolved:
                log(
                    "[captcha] case from font template (confidence {:.3f})".format(
                        font_confidence
                    )
                )
                return resolved

    # Tesseract already carries letters and case, so prefer it; ddddocr and the
    # plain engine consensus are the fallbacks.
    if tess_best:
        log("[captcha] read from tesseract (preprocessed)")
        return tess_best
    if dd_letters:
        return _ocr_shot(shot, config, prefix, verbose=False) or _clean(
            dd_letters, charset, length
        )
    return _ocr_shot(shot, config, prefix, verbose=False)


def _capture_sample(driver, config, prefix, shot, text):
    """Optionally save a located captcha crop for later labeling.

    Enabled by ``<prefix>_capture_samples``. The crop is stored unlabeled in
    ``dataset/permata/images``; ``bank/permata.py`` confirms it (adds the label)
    once the login succeeds. The saved path is kept on the driver so the caller
    can reach it after the OCR step.
    """
    if not config.get("{}_capture_samples".format(prefix)):
        return
    try:
        from utils import captcha_dataset

        path = captcha_dataset.save_sample(shot, config)
        if driver is not None:
            driver.last_captcha = {"path": path, "text": text}
        log("[captcha] saved captcha sample {}".format(os.path.basename(path)))
    except Exception as exc:
        log("[captcha] saving captcha sample failed: {}".format(exc))


def _ocr_shot(shot, config, prefix, verbose=True):
    """OCR an already-captured image and return the cleaned captcha text.

    ``<prefix>_ocr_engine``: ``auto`` (default) runs both engines and prefers
    Tesseract's case when the two agree on the letters (ddddocr is more accurate
    but lowercase-only; Tesseract preserves case); ``ddddocr`` or ``tesseract``
    forces one engine.
    """
    length = config.get("{}_captcha_length".format(prefix), 4)
    charset = config.get("{}_captcha_charset".format(prefix), DEFAULT_CHARSET)
    engine = (config.get("{}_ocr_engine".format(prefix)) or "auto").lower()

    raw_d = _ddddocr_read(shot) if engine in ("auto", "ddddocr") else None
    raw_t = (
        _tesseract_read(shot, config, prefix)
        if engine in ("auto", "tesseract")
        else None
    )
    d = _clean(raw_d, charset, length) if raw_d is not None else None
    t = _clean(raw_t, charset, length) if raw_t is not None else None

    if engine == "ddddocr":
        chosen = d
    elif engine == "tesseract":
        chosen = t
    elif t and (not d or t.lower() == d.lower()):
        # Prefer Tesseract's case when both engines read the same letters.
        chosen = t
    else:
        chosen = d or t

    if chosen:
        log("[captcha] OCR read {!r}".format(chosen))
        return chosen
    if verbose:
        if raw_d is not None:
            log("[captcha] ddddocr unusable (read {!r})".format(_safe(raw_d.strip())))
        if raw_t is not None:
            log("[captcha] tesseract unusable (read {!r})".format(_safe(raw_t.strip())))
    return None


def read_captcha_near(
    driver, config, timeout=None, scales=None, prefix="permata", solver=None
):
    """Locate the captcha by a reference image, then OCR the located region.

    The reference is matched at ``<prefix>_captcha_confidence`` (default 0.5)
    since the captcha letters differ from the saved reference. Up to
    ``<prefix>_captcha_candidates`` distinct candidate locations are tried and
    the first region whose OCR yields a valid captcha is returned, which avoids
    committing to a single wrong match. *solver* overrides the OCR step (e.g.
    ``read_captcha_permata`` for case-accurate reads); it defaults to
    ``_ocr_shot``. Returns the cleaned captcha text, or ``None`` when the
    reference image or an OCR engine is unavailable or no candidate produces a
    valid captcha.
    """
    if _get_ddddocr() is None and not _pytesseract_present():
        log("[captcha] no OCR engine available (install ddddocr or pytesseract)")
        return None

    name = config.get("{}_captcha_image".format(prefix), "captcha.JPG")
    confidence = config.get("{}_captcha_confidence".format(prefix), 0.5)
    limit = int(config.get("{}_captcha_candidates".format(prefix), 10))
    blur = int(config.get("{}_captcha_blur".format(prefix), 15) or 0)
    if scales is None:
        # The reference is captured on the same fixed screen, so locate at its
        # native scale; blurring makes downscaled templates match spurious areas.
        scales = config.get("{}_captcha_scales".format(prefix), [1.0])
    candidates = driver.locate_image_candidates(
        name,
        limit=limit,
        timeout=timeout,
        confidence=confidence,
        scales=scales,
        blur=blur,
    )
    if not candidates:
        log(
            "[captcha] captcha image not found ({}; confidence {:.2f})".format(
                name, confidence
            )
        )
        return None

    import pyautogui

    pad = int(config.get("{}_captcha_padding".format(prefix), 0))
    length = config.get("{}_captcha_length".format(prefix), 4)
    for center, score, size in candidates:
        region = _crop_region(center, size, pad)
        try:
            shot = pyautogui.screenshot(region=region)
        except Exception as exc:
            log("[captcha] screenshot of captcha region {} failed: {}".format(region, exc))
            continue
        text = solver(shot) if solver else _ocr_shot(shot, config, prefix, verbose=False)
        if text:
            log(
                "[captcha] located captcha ({}) at {} (score {:.2f})".format(
                    name, region, score
                )
            )
            _capture_sample(driver, config, prefix, shot, text)
            return text
    log(
        "[captcha] no candidate produced a {}-char captcha ({} candidates)".format(
            length, len(candidates)
        )
    )
    return None


def read_captcha(config, prefix="permata", solver=None, driver=None):
    """OCR a captcha from the configured fixed screen region.

    *solver* overrides the OCR step (see :func:`read_captcha_near`). *driver*,
    when given, receives the captured sample (``last_captcha``) so a login that
    succeeded through this fallback still labels the crop it actually used.
    Returns the cleaned string of the expected length, or ``None`` when the
    region is not configured, no OCR engine is available, or the OCR result
    cannot be resolved to the expected length.
    """
    region = _region(config, prefix)
    if region is None:
        log("[captcha] {} captcha region not configured".format(prefix))
        return None

    import pyautogui

    try:
        shot = pyautogui.screenshot(region=region)
    except Exception as exc:
        log("[captcha] screenshot of region {} failed: {}".format(region, exc))
        return None
    text = solver(shot) if solver else _ocr_shot(shot, config, prefix)
    if text:
        _capture_sample(driver, config, prefix, shot, text)
    return text
