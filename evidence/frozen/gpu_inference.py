"""Frozen DF-Arena raw-waveform speed diagnostic (64 sources x four views).

Example on a GPU host after copying the bundle, prepared WAVs and this file::

    python gpu_inference.py --baseline /content/dacon236749/baseline_run \
        --bundle-root /content/dacon236749 \
        --out /content/dacon236749/speed_probe_v1/result

The 0.8, 1.0 and 1.25 views are produced by prepare_audio.py, not this file.
This intentionally does not run PANNs, Demucs or the competition score formula.
It does not fit, tune or train any model. The raw voice score is diagnostic only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path


# Do not permit a model loader to fetch a missing file. Set before torch imports.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

EXPECTED_BASELINE_SCRIPT = "c17d776b7c17c2d70f1e55c2186ea54f0af8695dcdf07a106523cd80213aed9e"
EXPECTED_DF_ARENA_WEIGHT = "780bc14fd4c15e65d58efdef728427cf03cd29cd60be528e97badf8c89087988"
VARIANTS = ("original", "0.8", "1.0", "1.25")
RATE_NAMES = {"original": "original", "0.8": "atempo_0p8", "1.0": "atempo_1p0", "1.25": "atempo_1p25"}
RESULT_COLUMNS = (
    "id", "label", "generator", "variant", "rate_name", "input_path",
    "input_sha256", "duration_seconds", "samples", "segment_count",
    "tiled_short_segment", "raw_fake", "elapsed_seconds",
)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def write_csv_atomic(path: Path, rows: list[dict]) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def safe_bundle_file(bundle_root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe bundle path: {name}")
    resolved = (bundle_root / relative).resolve()
    if not resolved.is_relative_to(bundle_root):
        raise ValueError(f"Path escapes bundle: {name}")
    return resolved


def verify_baseline(baseline: Path) -> dict:
    script = baseline / "script.py"
    if sha256_file(script) != EXPECTED_BASELINE_SCRIPT:
        raise ValueError("Baseline script SHA-256 differs from the frozen reference")
    sums = baseline / "model" / "SHA256SUMS.txt"
    expected = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            expected[name.lstrip("*")] = digest.lower()
    weight_name = "df_arena_1b/pytorch_model.bin"
    if expected.get(weight_name) != EXPECTED_DF_ARENA_WEIGHT:
        raise ValueError("DF-Arena weight is not the frozen published model")
    weight = (baseline / "model" / weight_name).resolve()
    if not weight.is_relative_to((baseline / "model").resolve()):
        raise ValueError("DF-Arena weight path escapes model directory")
    if sha256_file(weight) != expected[weight_name]:
        raise ValueError("DF-Arena weight SHA-256 mismatch")
    code = {}
    for name in ("__init__.py", "modeling_antispoofing.py", "backbone.py", "conformer.py", "configuration_antispoofing.py", "config.json"):
        code[name] = sha256_file(baseline / "model" / "df_arena_1b" / name)
    return {
        "baseline_script_sha256": EXPECTED_BASELINE_SCRIPT,
        "df_arena_weight_sha256": EXPECTED_DF_ARENA_WEIGHT,
        "model_code_sha256": code,
    }


def verify_manifest_and_inputs(bundle_root: Path, manifest_path: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "passed" or manifest.get("source_count") != 64:
        raise ValueError("Expected passed preparation of exactly 64 full sources")
    if manifest.get("sample_rate") != 16000 or manifest.get("channels") != 1 or manifest.get("wav_encoding") != "IEEE_FLOAT32":
        raise ValueError("Unexpected prepared audio format")
    source_rows = manifest.get("rows", [])
    if len(source_rows) != 64 or {r.get("label") for r in source_rows} != {0, 1}:
        raise ValueError("Expected 64 labeled sources with both classes")
    if sum(r["label"] == 0 for r in source_rows) != 32 or sum(r["label"] == 1 for r in source_rows) != 32:
        raise ValueError("Expected 32 real and 32 AI sources")
    tasks = []
    seen_ids = set()
    seen_paths = set()
    for source in source_rows:
        source_id = source["id"]
        if source_id in seen_ids or not source_id:
            raise ValueError("Duplicate or empty source ID")
        seen_ids.add(source_id)
        if set(source["variants"]) != set(VARIANTS):
            raise ValueError(f"Missing view for {source_id}")
        for variant in VARIANTS:
            spec = source["variants"][variant]
            path = safe_bundle_file(bundle_root, spec["path"])
            if path in seen_paths:
                raise ValueError(f"Duplicate input path: {path}")
            seen_paths.add(path)
            if path.name != f"{source_id}__{RATE_NAMES[variant]}.wav":
                raise ValueError(f"Unexpected view filename: {path.name}")
            if sha256_file(path) != spec["sha256"]:
                raise ValueError(f"Prepared WAV SHA-256 mismatch: {path}")
            if not spec["finite"] or not spec["within_float_audio_range"] or spec["samples"] <= 0:
                raise ValueError(f"Invalid audio manifest entry: {path}")
            if variant != "original" and not spec.get("within_duration_tolerance"):
                raise ValueError(f"Audio duration failed preparation: {path}")
            tasks.append({
                "id": source_id,
                "label": source["label"],
                "generator": source["generator"],
                "variant": variant,
                "rate_name": RATE_NAMES[variant],
                "input_path": spec["path"],
                "input_sha256": spec["sha256"],
                "duration_seconds": spec["seconds"],
                "samples": spec["samples"],
                "_absolute_path": path,
            })
    if len(tasks) != 256:
        raise ValueError("Expected 256 prepared views")
    return manifest, tasks


def verify_protocol(protocol_path: Path, manifest_sha256: str) -> dict:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    model = protocol.get("model", {})
    if protocol.get("experiment") != "speed_probe_v1":
        raise ValueError("Unexpected frozen protocol")
    if protocol.get("inputs", {}).get("manifest_sha256") != manifest_sha256:
        raise ValueError("Protocol does not refer to these prepared inputs")
    if protocol.get("variants") != list(VARIANTS):
        raise ValueError("Protocol speed views differ from runner")
    if model.get("segment_samples") != 64600 or model.get("aggregation") != "original baseline maximum over segments":
        raise ValueError("Protocol model windowing differs from frozen baseline")
    if model.get("threshold") != .5 or model.get("training") is not False or model.get("threshold_tuning") is not False:
        raise ValueError("Protocol allows a different decision or model fit")
    if model.get("not_full_submission_pipeline") is not True:
        raise ValueError("Protocol misstates raw voice diagnostic scope")
    return protocol


def equal_error_rate(labels: list[int], scores: list[float]) -> float:
    """Tie-aware ROC EER with linear interpolation between operating points."""
    if len(labels) != len(scores) or set(labels) != {0, 1}:
        raise ValueError("EER requires equal-length scores and both classes")
    positives = sum(labels)
    negatives = len(labels) - positives
    by_score = sorted(zip(scores, labels), reverse=True)
    fpr = 0.0
    fnr = 1.0
    previous_delta = fpr - fnr
    index = 0
    while index < len(by_score):
        score = by_score[index][0]
        accepted_fake = accepted_real = 0
        while index < len(by_score) and by_score[index][0] == score:
            accepted_fake += by_score[index][1] == 1
            accepted_real += by_score[index][1] == 0
            index += 1
        next_fpr = fpr + accepted_real / negatives
        next_fnr = fnr - accepted_fake / positives
        next_delta = next_fpr - next_fnr
        if next_delta >= 0:
            if next_delta == previous_delta:
                return float((next_fpr + next_fnr) / 2)
            share = -previous_delta / (next_delta - previous_delta)
            return float(fpr + share * (next_fpr - fpr))
        fpr, fnr, previous_delta = next_fpr, next_fnr, next_delta
    raise AssertionError("ROC crossing absent")


def auc_rank(labels: list[int], scores: list[float]) -> float:
    positives = [s for y, s in zip(labels, scores) if y == 1]
    negatives = [s for y, s in zip(labels, scores) if y == 0]
    if not positives or not negatives:
        raise ValueError("AUC requires both classes")
    return sum(1 if p > n else .5 if p == n else 0 for p in positives for n in negatives) / (len(positives) * len(negatives))


def classification_metrics(rows: list[dict], score_key: str = "raw_fake") -> dict:
    labels = [int(row["label"]) for row in rows]
    scores = [float(row[score_key]) for row in rows]
    if len(rows) != 64 or len({row["id"] for row in rows}) != 64:
        raise ValueError("Metrics require 64 independent source IDs")
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in scores):
        raise ValueError("Scores must be finite probabilities")
    tp = sum(y == 1 and p >= .5 for y, p in zip(labels, scores))
    fp = sum(y == 0 and p >= .5 for y, p in zip(labels, scores))
    fn = sum(y == 1 and p < .5 for y, p in zip(labels, scores))
    tn = sum(y == 0 and p < .5 for y, p in zip(labels, scores))
    return {
        "n": len(rows),
        "real": tn + fp,
        "ai": tp + fn,
        "threshold": .5,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive_rate": fp / (fp + tn),
        "false_negative_rate": fn / (fn + tp),
        "balanced_accuracy": .5 * (tp / (tp + fn) + tn / (tn + fp)),
        "eer": equal_error_rate(labels, scores),
        "auc": auc_rank(labels, scores),
    }


def summarize(rows: list[dict], manifest: dict, provenance: dict) -> dict:
    by_key = {(r["id"], r["variant"]): r for r in rows}
    metrics = {}
    for variant in VARIANTS:
        subset = [by_key[(item["id"], variant)] for item in manifest["rows"]]
        metrics[variant] = classification_metrics(subset)
    ensemble = []
    shifts = {}
    for item in manifest["rows"]:
        source_id = item["id"]
        original = by_key[(source_id, "original")]
        # Declared before seeing predictions: simple mean, equal weights, no fit.
        mean_score = sum(by_key[(source_id, v)]["raw_fake"] for v in ("original", "0.8", "1.25")) / 3
        ensemble.append({"id": source_id, "label": item["label"], "raw_fake": mean_score})
    metrics["predeclared_mean_original_0p8_1p25"] = classification_metrics(ensemble)
    for variant in ("0.8", "1.0", "1.25"):
        pairs = [(by_key[(item["id"], variant)]["raw_fake"], by_key[(item["id"], "original")]["raw_fake"], item["label"]) for item in manifest["rows"]]
        differences = [p - ref for p, ref, _ in pairs]
        shifts[variant] = {
            "mean_absolute": sum(abs(x) for x in differences) / len(differences),
            "max_absolute": max(abs(x) for x in differences),
            "mean_signed_real": sum(p - ref for p, ref, y in pairs if y == 0) / 32,
            "mean_signed_ai": sum(p - ref for p, ref, y in pairs if y == 1) / 32,
        }
    return {
        "scope": "Exploratory full-source raw-waveform voice DF-Arena diagnostic; no PANNs/Demucs, no ADS or official validation",
        "source_count": 64,
        "variant_count": len(rows),
        "protocol": "Fixed 0.8/1.0/1.25 atempo views; original control; frozen model; fixed threshold 0.5; equal-weight original/0.8/1.25 ensemble; no training or threshold tuning.",
        "metrics": metrics,
        "paired_score_shifts_vs_original": shifts,
        "prediction_elapsed_seconds": sum(r["elapsed_seconds"] for r in rows),
        "segment_passes": sum(r["segment_count"] for r in rows),
        "provenance": provenance,
    }


def checkpoint_rows(checkpoint: Path, expected: dict, tasks: list[dict]) -> list[dict]:
    if not checkpoint.exists():
        return []
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    if saved.get("schema") != 1 or saved.get("provenance") != expected:
        raise ValueError("Checkpoint provenance differs; use a new --out directory")
    rows = saved.get("rows", [])
    if len(rows) > len(tasks):
        raise ValueError("Checkpoint has too many rows")
    for row, task in zip(rows, tasks):
        for key in ("id", "label", "generator", "variant", "rate_name", "input_path", "input_sha256", "samples"):
            if row.get(key) != task[key]:
                raise ValueError(f"Checkpoint task mismatch at {task['id']} {task['variant']}")
        score = row.get("raw_fake")
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Checkpoint contains invalid score")
    return rows


def run(args: argparse.Namespace) -> None:
    bundle_root = args.bundle_root.resolve()
    baseline = args.baseline.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_root / "outputs" / "speed_probe_v1" / "prep_manifest.json"
    protocol_path = bundle_root / "outputs" / "speed_probe_v1" / "protocol.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing prepared manifest: {manifest_path}")
    manifest_hash = sha256_file(manifest_path)
    verify_protocol(protocol_path, manifest_hash)
    baseline_info = verify_baseline(baseline)
    manifest, tasks = verify_manifest_and_inputs(bundle_root, manifest_path)
    provenance = {
        "prep_manifest_sha256": manifest_hash,
        "protocol_sha256": sha256_file(protocol_path),
        "ffmpeg_sha256": manifest["ffmpeg_sha256"],
        "runner_sha256": sha256_file(Path(__file__)),
        **baseline_info,
    }
    checkpoint = out / "partial_results.json"
    partial_csv = out / "partial_results.csv"
    if (out / "results.json").exists():
        raise RuntimeError("Final result exists; refusing to overwrite it")
    rows = checkpoint_rows(checkpoint, provenance, tasks)
    print(f"Verified {len(tasks)} views and frozen model. Resume at {len(rows)}/{len(tasks)}.", flush=True)

    import numpy as np
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable; no CPU or paid-service fallback")
    def refuse_network(event: str, _arguments: tuple) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            raise RuntimeError(f"Unexpected network access during frozen inference: {event}")

    sys.addaudithook(refuse_network)
    random.seed(20260929)
    np.random.seed(20260929)
    torch.manual_seed(20260929)
    torch.cuda.manual_seed_all(20260929)
    torch.set_default_dtype(torch.float32)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    device = torch.device("cuda")
    try:
        transformers_version = importlib.metadata.version("transformers")
    except importlib.metadata.PackageNotFoundError:
        transformers_version = None
    runtime = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": str(torch.__version__),
        "transformers": transformers_version,
        "gpu": torch.cuda.get_device_name(device),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "float_precision": "FP32 with TF32 disabled",
    }
    previous_runtimes = json.loads(checkpoint.read_text(encoding="utf-8")).get("runtime_runs", []) if checkpoint.exists() else []
    if not isinstance(previous_runtimes, list):
        raise ValueError("Checkpoint runtime history is invalid")
    runtime_runs = [*previous_runtimes, runtime]
    module_name = "frozen_baseline_speed_probe"
    spec = importlib.util.spec_from_file_location(module_name, baseline / "script.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load frozen baseline script")
    frozen = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = frozen
    spec.loader.exec_module(frozen)
    model, fake_label_index = frozen.load_df_arena_model(device)
    if next(model.parameters()).dtype != torch.float32 or model.training:
        raise RuntimeError("Frozen DF-Arena must run in eval mode with FP32 weights")
    for index in range(len(rows), len(tasks)):
        task = tasks[index]
        start = time.perf_counter()
        audio = frozen.load_audio(task["_absolute_path"])
        if audio.dtype != np.float32 or audio.ndim != 1 or audio.size != task["samples"]:
            raise ValueError(f"Decoded WAV differs from manifest: {task['input_path']}")
        starts = frozen.get_segment_starts(audio.size)
        score = float(frozen.predict_fake(model, fake_label_index, audio, device))
        torch.cuda.synchronize()
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"Invalid model probability: {task['id']} {task['variant']}")
        result = {key: task[key] for key in RESULT_COLUMNS if key in task}
        result.update({
            "segment_count": len(starts) if frozen.calculate_rms(audio) >= frozen.SILENCE_RMS else 0,
            "tiled_short_segment": bool(audio.size < frozen.SEGMENT_SAMPLES),
            "raw_fake": score,
            "elapsed_seconds": time.perf_counter() - start,
        })
        rows.append(result)
        write_json_atomic(checkpoint, {"schema": 1, "provenance": provenance, "runtime_runs": runtime_runs, "rows": rows})
        write_csv_atomic(partial_csv, rows)
        print(f"{index + 1}/{len(tasks)} {task['id']} {task['variant']} score={score:.6f}", flush=True)
    report = summarize(rows, manifest, provenance)
    report["runtime_runs"] = runtime_runs
    write_json_atomic(out / "summary.json", report)
    write_json_atomic(out / "results.json", {"schema": 1, "provenance": provenance, "runtime_runs": runtime_runs, "rows": rows})
    write_csv_atomic(out / "results.csv", rows)
    print(json.dumps({"status": "complete", "metrics": report["metrics"]}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Frozen extracted baseline_run with script.py and model/")
    parser.add_argument("--bundle-root", type=Path, required=True, help="Directory containing outputs/speed_probe_v1 and work/speed_probe_v1/audio")
    parser.add_argument("--out", type=Path, required=True, help="New directory for resumable results")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
