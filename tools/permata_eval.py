"""Evaluate the PERMATA captcha solver over the labeled dataset (CPU only).

Runs ``utils/captcha.read_captcha_permata`` on every labeled crop and reports
the numbers that matter: case-sensitive full-string accuracy (the one the bank
checks), case-insensitive letter accuracy, per-character accuracy and a
confusion report. Mismatches are copied to ``dataset/permata/misses`` for
inspection. Use it to tune the preprocessing variants and the font-template
thresholds -- this is the feedback loop; no GPU is needed.

Usage:
    python tools/permata_eval.py
    python tools/permata_eval.py --mode font --show 40
    python tools/permata_eval.py --holdout 20
"""

import argparse
import json
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils import captcha, captcha_dataset  # noqa: E402


def load_config(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def evaluate(samples, config, prefix):
    """Run the solver over *samples*; returns a stats dict."""
    from PIL import Image

    stats = {
        "total": 0,
        "exact": 0,
        "letters": 0,
        "pos_total": 0,
        "pos_correct": 0,
        "confusion": {},
        "misses": [],
    }
    for path, label in samples:
        try:
            shot = Image.open(path)
        except Exception as exc:
            print("  ! cannot open {}: {}".format(path, exc))
            continue
        prediction = captcha.read_captcha_permata(shot, config, prefix=prefix)
        stats["total"] += 1
        if prediction == label:
            stats["exact"] += 1
        if prediction and prediction.lower() == label.lower():
            stats["letters"] += 1
        if prediction and len(prediction) == len(label):
            for expected, actual in zip(label, prediction):
                stats["pos_total"] += 1
                if expected == actual:
                    stats["pos_correct"] += 1
                else:
                    key = "{}->{}".format(expected, actual)
                    stats["confusion"][key] = stats["confusion"].get(key, 0) + 1
        if prediction != label:
            stats["misses"].append((path, label, prediction))
    return stats


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_token(text):
    """Sanitize a label/prediction for use inside a filename."""
    token = _UNSAFE_CHARS.sub("_", text or "none")[:32]
    return token or "none"


def save_misses(misses, config, show):
    if not misses:
        return
    target = os.path.abspath(captcha_dataset.misses_dir(config))
    os.makedirs(target, exist_ok=True)
    for path, label, prediction in misses[:show]:
        name = "actual-{}_pred-{}_{}".format(
            _safe_token(label), _safe_token(prediction), os.path.basename(path)
        )
        dest = os.path.abspath(os.path.join(target, name))
        # Confine the copy to the misses directory even if dataset/OCR values
        # contain separators.
        try:
            if os.path.commonpath([dest, target]) != target:
                continue
        except ValueError:
            continue
        try:
            shutil.copyfile(path, dest)
        except OSError:
            pass


def report(stats, title):
    total = stats["total"]
    print("\n=== {} ===".format(title))
    if not total:
        print("no samples")
        return
    print("samples                : {}".format(total))
    print(
        "case-sensitive accuracy: {}/{} = {:.1%}".format(
            stats["exact"], total, stats["exact"] / total
        )
    )
    print(
        "letter accuracy (case-) : {}/{} = {:.1%}".format(
            stats["letters"], total, stats["letters"] / total
        )
    )
    if stats["pos_total"]:
        print(
            "per-character accuracy  : {}/{} = {:.1%}".format(
                stats["pos_correct"],
                stats["pos_total"],
                stats["pos_correct"] / stats["pos_total"],
            )
        )
    if stats["confusion"]:
        ranked = sorted(stats["confusion"].items(), key=lambda kv: -kv[1])
        print("top confusions          :")
        for key, count in ranked[:12]:
            print("    {:>3}x  {}".format(count, key))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", help="dataset directory (default from config)")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"))
    parser.add_argument("--prefix", default="permata")
    parser.add_argument(
        "--mode",
        choices=["auto", "font", "tesseract", "baseline"],
        help="override permata_case_mode for this run",
    )
    parser.add_argument("--limit", type=int, default=None, help="max samples to use")
    parser.add_argument(
        "--holdout",
        type=int,
        default=0,
        help="evaluate only the last N samples (held-out slice)",
    )
    parser.add_argument("--show", type=int, default=25, help="miss crops to copy")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.dataset:
        config["permata_dataset_dir"] = args.dataset
    if args.mode:
        config["{}_case_mode".format(args.prefix)] = args.mode

    samples = list(captcha_dataset.iter_samples(config=config, limit=args.limit))
    if args.holdout:
        samples = samples[-args.holdout :]
    if not samples:
        print(
            "No labeled samples found. Add crops to dataset/permata/images and "
            "rows to dataset/permata/labels.txt."
        )
        return 1

    mode = config.get("{}_case_mode".format(args.prefix), "auto")
    stats = evaluate(samples, config, args.prefix)
    report(stats, "permata captcha (case_mode={})".format(mode))
    if stats["misses"]:
        save_misses(stats["misses"], config, args.show)
        print(
            "\n{} misses copied to {}".format(
                min(len(stats["misses"]), args.show), captcha_dataset.misses_dir(config)
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
