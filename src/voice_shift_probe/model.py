"""Adapter to a separately obtained frozen baseline; no third-party model redistribution."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from .audio import file_hash, paired_views, pcm_hash, SR
from .patterns import features

SCRIPT_HASH = "c17d776b7c17c2d70f1e55c2186ea54f0af8695dcdf07a106523cd80213aed9e"
WEIGHT_HASH = "780bc14fd4c15e65d58efdef728427cf03cd29cd60be528e97badf8c89087988"


class FrozenDFBackend:
    """Use the exact baseline loader and windowing; load externally licensed files locally."""

    def __init__(self, baseline, device="cuda"):
        baseline = Path(baseline).resolve()
        script = baseline / "script.py"
        weight = baseline / "model/df_arena_1b/pytorch_model.bin"
        if file_hash(script) != SCRIPT_HASH or file_hash(weight) != WEIGHT_HASH:
            raise ValueError("Baseline script or DF-Arena checkpoint differs from the frozen reference")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable. No automatic paid or CPU fallback.")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        spec = importlib.util.spec_from_file_location("_voice_shift_frozen_baseline", script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.device = torch.device(device)
        self.module = module
        self.model, self.fake_label = module.load_df_arena_model(self.device)
        if self.model.training or next(self.model.parameters()).dtype != torch.float32:
            raise ValueError("Expected eval mode and FP32 weights")

    def score(self, wave):
        score = float(self.module.predict_fake(self.model, self.fake_label, wave, self.device))
        count = 0 if self.module.calculate_rms(wave) < self.module.SILENCE_RMS else len(self.module.get_segment_starts(len(wave)))
        return score, count


def probe(wave, backend, executable):
    """Four diagnostic views + three-view score mean; pattern features are not classifier inputs."""
    rows = []
    for name, audio in paired_views(wave, executable).items():
        score, count = backend.score(audio)
        if not 0 <= score <= 1:
            raise ValueError("Backend returned an invalid score")
        rate = 1.0 if name == "original" else float(name)
        try:
            pattern = features(audio, rate)
        except ValueError:
            pattern = None  # Very short clips cannot support the fixed 0.25-2s lag range.
        rows.append({"variant": name, "raw_fake": score, "segment_count": count,
                     "samples": len(audio), "duration_seconds": len(audio) / SR,
                     "pcm_sha256": pcm_hash(audio), "pattern_features": pattern})
    lookup = {r["variant"]: r for r in rows}
    mean = sum(lookup[v]["raw_fake"] for v in ("original", "0.8", "1.25")) / 3
    return {"research_only": True, "views": rows, "mean_score": mean,
            "control_1p0_score_shift": lookup["1.0"]["raw_fake"] - lookup["original"]["raw_fake"],
            "decision": None, "calibration": "Not validated; scores are not calibrated AI probabilities",
            "breath_detector": False}
