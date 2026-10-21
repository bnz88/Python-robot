"""Identify the PERMATA captcha font from a small labeled dataset (CPU only).

Renders the known label of each labeled captcha sample in candidate fonts and
scores how well the rendered glyphs match the captured ones. The best
``(font, size, rotation)`` is written to ``assets/permata/font.json`` for the
runtime case resolver (``utils/captcha.read_captcha_permata``). If no font
scores above the threshold the file is not written and the resolver falls back
to the Tesseract consensus.

No model training and no GPU: the labeled set can be small (30-60+ samples).

Usage:
    python tools/permata_font_id.py
    python tools/permata_font_id.py --fonts arial.ttf,verdana.ttf --top 15
    python tools/permata_font_id.py --force     # write even below the threshold
"""

import argparse
import datetime
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils import captcha_dataset, captcha_font as cf  # noqa: E402


def load_config(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    default = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(default):
        with open(default, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def parse_floats(text):
    return [float(part) for part in str(text).split(",") if part.strip()]


def parse_ints(text):
    return [int(part) for part in str(text).split(",") if part.strip()]


def load_work_samples(config, limit):
    """Load labeled crops segmented and normalized into per-character glyphs.

    Returns a list of ``(label, [normalized_glyph, ...])`` where the number of
    glyphs matches the label length (shared segmentation: connected components
    first, equal split as a fallback); skips samples that cannot be segmented
    cleanly.
    """
    from PIL import Image

    samples = []
    skipped = 0
    for path, label in captcha_dataset.iter_samples(config=config, limit=limit):
        try:
            gray = cf.to_gray(Image.open(path))
        except Exception:
            skipped += 1
            continue
        # Shared segmentation, so the font is chosen against the exact glyphs
        # the runtime resolver will use.
        glyphs = cf.segment_label(gray, label)
        if not glyphs:
            skipped += 1
            continue
        # Normalize the captured glyphs once; score_font reuses them for every
        # candidate font/size/rotation.
        normalized = [cf.normalize_glyph(glyph) for glyph in glyphs]
        samples.append((label, normalized))
    return samples, skipped


def score_font(font_path, size, rotation, samples):
    """Mean glyph similarity of *samples* rendered in the font at this setting.

    *samples* carry already-normalized captured glyphs; only the rendered
    templates are normalized per candidate (and cached per character).
    """
    try:
        font = cf.load_pil_font(font_path, size)
    except Exception:
        return 0.0
    total = 0.0
    count = 0
    rendered_cache = {}
    for label, glyphs_norm in samples:
        for index, char in enumerate(label):
            key = char
            if key not in rendered_cache:
                rendered_cache[key] = cf.normalize_glyph(
                    cf.render_glyph(font, char, rotation)
                )
            total += cf.similarity_normalized(glyphs_norm[index], rendered_cache[key])
            count += 1
    return total / count if count else 0.0


def candidate_fonts(args):
    if args.fonts:
        resolved = []
        for name in str(args.fonts).split(","):
            name = name.strip()
            if not name:
                continue
            path = cf.resolve_font(name)
            if path:
                resolved.append(path)
            else:
                print("  ! font not found: {}".format(name))
        return resolved
    fonts = cf.list_system_fonts()
    if args.max_fonts:
        fonts = fonts[: args.max_fonts]
    return fonts


def default_sizes(samples):
    heights = sorted(len(glyphs[0]) for _, glyphs in samples)
    median = heights[len(heights) // 2] if heights else 32
    return sorted({max(8, int(median * factor)) for factor in (0.7, 0.85, 1.0, 1.2, 1.4)})


def refine(font_path, sizes, rotations, samples):
    """Full search over sizes/rotations for one font; returns best (score, size, rot)."""
    best = (0.0, sizes[0], 0.0)
    for size in sizes:
        for rotation in rotations:
            value = score_font(font_path, size, rotation, samples)
            if value > best[0]:
                best = (value, size, rotation)
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", help="dataset directory (default from config)")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"))
    parser.add_argument("--fonts", help="comma-separated font names/paths to try")
    parser.add_argument("--font-file", help="write the result to this path")
    parser.add_argument("--sizes", help="comma-separated render sizes (default: derived)")
    parser.add_argument(
        "--rotations", default="0,-6,6", help="comma-separated rotations in degrees"
    )
    parser.add_argument("--samples", type=int, default=40, help="max samples to use")
    parser.add_argument("--max-fonts", type=int, default=None, help="cap candidate fonts")
    parser.add_argument("--candidates", type=int, default=8, help="fonts taken into refine")
    parser.add_argument("--top", type=int, default=10, help="ranking lines to print")
    parser.add_argument(
        "--min-score", type=float, default=0.5, help="acceptance threshold"
    )
    parser.add_argument("--force", action="store_true", help="write below threshold too")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.dataset:
        config["permata_dataset_dir"] = args.dataset

    samples, skipped = load_work_samples(config, args.samples)
    print("samples: {} usable, {} skipped".format(len(samples), skipped))
    if len(samples) < 3:
        print(
            "Not enough labeled samples (need >= 3). Add crops to "
            "dataset/permata/images and rows to dataset/permata/labels.txt."
        )
        return 1

    sizes = parse_ints(args.sizes) if args.sizes else default_sizes(samples)
    rotations = parse_floats(args.rotations)
    fonts = candidate_fonts(args)
    print(
        "candidate fonts: {}; sizes: {}; rotations: {}".format(
            len(fonts), sizes, rotations
        )
    )
    if not fonts:
        print("No candidate fonts found.")
        return 1

    # Pass 1 (coarse): one size, no rotation, a subset of samples.
    coarse_samples = samples[: min(6, len(samples))]
    coarse_size = sizes[len(sizes) // 2]
    ranked = []
    for font_path in fonts:
        value = score_font(font_path, coarse_size, 0.0, coarse_samples)
        ranked.append((value, font_path))
    ranked.sort(reverse=True)

    # Pass 2 (refine): full size/rotation search on the top candidates.
    refined = []
    for _, font_path in ranked[: max(1, args.candidates)]:
        value, size, rotation = refine(font_path, sizes, rotations, samples)
        refined.append((value, font_path, size, rotation))
    refined.sort(key=lambda row: row[0], reverse=True)

    print("\nTop results:")
    for values in refined[: args.top]:
        value, font_path, size, rotation = values
        print(
            "  {:.3f}  {}  (size {}, rotation {})".format(
                value, os.path.basename(font_path), size, rotation
            )
        )

    best_score, best_font, best_size, best_rotation = refined[0]
    if best_score < args.min_score and not args.force:
        print(
            "\nFont not identified (best score {:.3f} < {:.2f}). "
            "The resolver will use the Tesseract consensus; add more labeled "
            "samples and retry, or pass --force to write anyway.".format(
                best_score, args.min_score
            )
        )
        return 2

    out_path = (
        args.font_file
        or config.get("permata_font_file")
        or os.path.join("assets", "permata", "font.json")
    )
    if not os.path.isabs(out_path):
        out_path = os.path.join(BASE_DIR, out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = {
        "font": best_font,
        "font_name": os.path.basename(best_font),
        "size": int(best_size),
        "rotation": float(best_rotation),
        "score": round(float(best_score), 4),
        "samples": len(samples),
        "generated": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="seconds"),
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(
        "\nWrote {} (score {:.3f}, size {}, rotation {}).".format(
            out_path, best_score, best_size, best_rotation
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
