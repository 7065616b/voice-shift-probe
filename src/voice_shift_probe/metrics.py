"""Score metrics with grouped ties; positive label 1 means AI-generated."""

from __future__ import annotations

import math


def validate(labels, scores):
    if len(labels) != len(scores) or set(labels) != {0, 1}:
        raise ValueError("Scores need matching binary labels and both classes")
    if any(type(y) is not int for y in labels):
        raise ValueError("Labels must be integer 0 or 1")
    if not all(math.isfinite(s) and 0 <= s <= 1 for s in scores):
        raise ValueError("Scores must be finite and within [0, 1]")


def eer(labels, scores):
    """Linear interpolation of ROC crossing; not the contest's nearest-point EER."""
    validate(labels, scores)
    groups = {}
    for label, score in zip(labels, scores):
        groups.setdefault(score, []).append(label)
    real, fake = labels.count(0), labels.count(1)
    false_alarms, misses = 0, fake
    previous_far, previous_miss = 0.0, 1.0
    for score in sorted(groups, reverse=True):
        false_alarms += groups[score].count(0)
        misses -= groups[score].count(1)
        far, miss = false_alarms / real, misses / fake
        before, after = previous_far - previous_miss, far - miss
        if after >= 0:
            fraction = -before / (after - before)
            return previous_far + fraction * (far - previous_far)
        previous_far, previous_miss = far, miss
    raise AssertionError("ROC crossing missing")


def metrics(labels, scores, threshold=0.5):
    validate(labels, scores)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must be within [0, 1]")
    real = [s for y, s in zip(labels, scores) if y == 0]
    fake = [s for y, s in zip(labels, scores) if y == 1]
    tp = sum(s >= threshold for s in fake)
    fp = sum(s >= threshold for s in real)
    fn, tn = len(fake) - tp, len(real) - fp
    auc = sum(1 if f > r else 0.5 if f == r else 0 for f in fake for r in real)
    return {
        "n": len(labels), "real": len(real), "ai": len(fake), "threshold": threshold,
        "true_positive": tp, "false_positive": fp, "false_negative": fn,
        "true_negative": tn, "false_positive_rate": fp / len(real),
        "false_negative_rate": fn / len(fake),
        "balanced_accuracy": (tp / len(fake) + tn / len(real)) / 2,
        "eer": eer(labels, scores), "auc": auc / (len(real) * len(fake)),
    }


VIEWS = ("original", "0.8", "1.0", "1.25")
MEAN_NAME = "predeclared_mean_original_0p8_1p25"


def summarize_rows(rows):
    """Group derivatives by source; never count views as independent recordings."""
    sources = {}
    for row in rows:
        source = sources.setdefault(row["id"], {})
        if row["variant"] not in VIEWS or row["variant"] in source:
            raise ValueError("Unknown or duplicate source view")
        if type(row["label"]) is not int or row["label"] not in (0, 1):
            raise ValueError("Invalid label")
        source[row["variant"]] = row
    if not sources:
        raise ValueError("No source rows")
    for source in sources.values():
        if set(source) != set(VIEWS):
            raise ValueError("Each source must have all four views")
        if len({r["label"] for r in source.values()}) != 1:
            raise ValueError("Labels changed across paired views")
        if len({r["generator"] for r in source.values()}) != 1:
            raise ValueError("Generator changed across paired views")
    ordered = [sources[key] for key in sorted(sources)]
    labels = [s["original"]["label"] for s in ordered]
    report = {v: metrics(labels, [float(s[v]["raw_fake"]) for s in ordered]) for v in VIEWS}
    means = [sum(float(s[v]["raw_fake"]) for v in ("original", "0.8", "1.25")) / 3
             for s in ordered]
    report[MEAN_NAME] = metrics(labels, means)
    return report
