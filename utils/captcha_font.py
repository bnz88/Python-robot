"""Image and font primitives for training-free PERMATA captcha case resolution.

The PERMATA login captcha is a mixed-case alphanumeric image and the site is
case-sensitive, but the bundled ddddocr model emits lowercase only. Instead of
training a model (needs a GPU), the case of each glyph is resolved by comparing
the captured glyph against the same character rendered in the captcha's own
font, in both cases. These helpers do the image work: segmentation, glyph
normalization/similarity, font discovery and rendering, and rotation.

Used by ``utils.captcha`` at runtime and by the offline tools in ``tools/``.
Requires ``opencv-python``, ``numpy`` and ``pillow`` (already project deps).
"""

import glob
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

GLYPH_SIZE = 32
"""Side (px) every glyph is normalized to before comparison."""


def to_gray(image):
    """Return a uint8 grayscale ndarray from a PIL image or ndarray."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return image.astype(np.uint8, copy=False)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return np.array(image.convert("L"))


def binarize(gray, invert=True):
    """Otsu-threshold *gray* to a uint8 mask with foreground set to 255.

    ``invert`` assumes dark glyphs on a light background (the usual captcha
    case): after Otsu the light background is white, so it is inverted to leave
    the glyphs white.
    """
    if gray.dtype != np.uint8:
        gray = gray.astype(np.uint8)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return (255 - mask) if invert else mask


def content_box(gray, pad=2):
    """Bounding box (x0, y0, x1, y1) of the foreground, or None when empty."""
    fg = binarize(gray, invert=True)
    ys, xs = np.where(fg > 0)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(gray.shape[1] - 1, x1 + pad)
    y1 = min(gray.shape[0] - 1, y1 + pad)
    return x0, y0, x1, y1


def split_equal(gray, count):
    """Split the foreground into *count* equal-width columns (fallback).

    Returns a list of grayscale crops, or None when there is no foreground.
    Used when connected-component segmentation does not yield exactly *count*
    glyphs (e.g. touching characters).
    """
    box = content_box(gray)
    if box is None or count <= 0:
        return None
    x0, y0, x1, y1 = box
    width = (x1 - x0 + 1) / float(count)
    crops = []
    for index in range(count):
        left = int(round(x0 + index * width))
        right = int(round(x0 + (index + 1) * width))
        if right <= left:
            return None
        crops.append(gray[y0 : y1 + 1, left:right])
    return crops


def segment_glyphs(gray, max_glyphs=12, min_area=12, blur=5):
    """Segment a captcha into left-to-right glyph crops (grayscale uint8).

    A light blur and a morphological opening remove the thin wavy noise lines
    many captchas draw through the glyphs; connected components are then taken
    and filtered by area/height so specks and full-frame blobs are dropped.
    """
    work = gray
    if blur and blur >= 3:
        size = blur if blur % 2 == 1 else blur + 1
        work = cv2.GaussianBlur(work, (size, size), 0)
    fg = binarize(work, invert=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    opened = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(
        opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    height = gray.shape[0]
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area:
            continue
        if h < height * 0.25 or h > height * 0.98:
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: box[0])
    return [gray[y : y + h, x : x + w] for x, y, w, h in boxes[:max_glyphs]]


def segment_label(gray, label, max_extra=2, min_glyphs=6, blur=5):
    """Segment *gray* into exactly ``len(label)`` glyph crops, or None.

    Connected components are tried first; when they do not yield the expected
    count (e.g. touching characters) the content is split into equal columns.
    Shared by the runtime resolver and the font tool so both see the identical
    segmentation, which keeps font identification consistent with runtime.
    """
    glyphs = segment_glyphs(
        gray, max_glyphs=max(len(label) + max_extra, min_glyphs), blur=blur
    )
    if len(glyphs) != len(label):
        glyphs = split_equal(gray, len(label))
    if not glyphs or len(glyphs) != len(label):
        return None
    return glyphs


def _normalize(glyph, size=GLYPH_SIZE):
    """Crop a glyph to its content and resize to *size*×*size*, in [0, 1]."""
    mask = binarize(glyph, invert=True)
    ys, xs = np.where(mask > 0)
    if len(xs):
        mask = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    resized = cv2.resize(mask, (size, size), interpolation=cv2.INTER_AREA)
    return resized.astype(np.float32) / 255.0


def normalize_glyph(glyph, size=GLYPH_SIZE):
    """Public wrapper: normalize a glyph crop for :func:`similarity_normalized`.

    Exposed so callers that compare one glyph against many candidates (e.g. the
    font tool) can normalize the fixed glyph once and reuse it.
    """
    return _normalize(glyph, size)


def similarity_normalized(na, nb):
    """Similarity in [0, 1] between two already-normalized glyph arrays."""
    va = na.ravel() - na.mean()
    vb = nb.ravel() - nb.mean()
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    ncc = float(np.dot(va, vb) / denom) if denom > 1e-6 else 0.0
    ncc = max(0.0, min(1.0, ncc))
    ma = na >= 0.5
    mb = nb >= 0.5
    union = int(np.logical_or(ma, mb).sum())
    iou = float(np.logical_and(ma, mb).sum()) / float(union) if union else 0.0
    return 0.5 * ncc + 0.5 * iou


def glyph_similarity(a, b, size=GLYPH_SIZE):
    """Similarity in [0, 1] between two glyph crops (1 = identical shape).

    Combines the (clamped) normalized cross-correlation with the IoU of the
    binarized masks, so both the gray structure and the shape matter.
    """
    return similarity_normalized(_normalize(a, size), _normalize(b, size))



def rotate(gray, angle):
    """Rotate *gray* by *angle* degrees, expanding the canvas, border = white."""
    if not angle:
        return gray
    height, width = gray.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(height * sin + width * cos)
    new_h = int(height * cos + width * sin)
    matrix[0, 2] += new_w / 2.0 - center[0]
    matrix[1, 2] += new_h / 2.0 - center[1]
    border = 255 if int(np.median(gray)) > 127 else 0
    return cv2.warpAffine(
        gray, matrix, (new_w, new_h), borderValue=border
    )


def load_pil_font(path, size):
    """Load a TrueType/OpenType font at *size* pixels."""
    return ImageFont.truetype(path, size)


def render_text(font, text, rotation=0.0, pad=8):
    """Render *text* (dark on white) to a grayscale ndarray.

    The result is tightly padded by *pad* px and optionally rotated, so it can
    be compared against a captured glyph with :func:`glyph_similarity`.
    """
    probe = Image.new("L", (10, 10), 255)
    draw = ImageDraw.Draw(probe)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
    except AttributeError:  # very old Pillow
        width, height = draw.textsize(text, font=font)
        bbox = (0, 0, width, height)
    width = max(1, bbox[2] - bbox[0]) + 2 * pad
    height = max(1, bbox[3] - bbox[1]) + 2 * pad
    canvas = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(canvas)
    draw.text((pad - bbox[0], pad - bbox[1]), text, fill=0, font=font)
    array = np.array(canvas)
    return rotate(array, rotation) if rotation else array


def render_glyph(font, char, rotation=0.0):
    """Render a single character (thin wrapper over :func:`render_text`)."""
    return render_text(font, char, rotation=rotation)


def system_font_dirs():
    """Directories searched for installed fonts."""
    dirs = []
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        dirs.extend(
            [
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                os.path.expanduser("~/.fonts"),
                os.path.expanduser("~/.local/share/fonts"),
            ]
        )
    return [d for d in dirs if d and os.path.isdir(d)]


def list_system_fonts():
    """All installed font files (ttf/otf/ttc), sorted and de-duplicated."""
    files = []
    for directory in system_font_dirs():
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            files.extend(glob.glob(os.path.join(directory, "**", ext), recursive=True))
    return sorted(set(files))


def resolve_font(name):
    """Resolve a font config value to an existing font file path, or None.

    Accepts an absolute path, a path relative to the working directory, a bare
    file name found in the system font directories, or a bare font stem (e.g.
    ``arial``).
    """
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    if os.path.exists(name):
        return os.path.abspath(name)
    base = os.path.basename(name)
    for directory in system_font_dirs():
        direct = os.path.join(directory, base)
        if os.path.exists(direct):
            return direct
        hits = glob.glob(os.path.join(directory, "**", base), recursive=True)
        if hits:
            return hits[0]
    stem = os.path.splitext(base)[0].lower()
    for font_file in list_system_fonts():
        if os.path.splitext(os.path.basename(font_file))[0].lower() == stem:
            return font_file
    return None
