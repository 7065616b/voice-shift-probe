from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np

from voice_shift_probe.audio import paired_views, resolve_ffmpeg
from voice_shift_probe.evidence import audit_evidence
from voice_shift_probe.metrics import eer, metrics, summarize_rows
from voice_shift_probe.model import probe
from voice_shift_probe.patterns import features

ROOT = Path(__file__).resolve().parents[1]


class ScoreTests(unittest.TestCase):
    def test_ties_perfect_and_reversed(self):
        self.assertEqual(eer([0, 1], [0.5, 0.5]), 0.5)
        self.assertEqual(eer([0, 1], [0.1, 0.9]), 0.0)
        self.assertEqual(eer([0, 1], [0.9, 0.1]), 1.0)
        self.assertEqual(metrics([0, 1], [0.5, 0.5])["auc"], 0.5)

    def test_threshold_errors_can_worsen_while_ranking_improves(self):
        labels = [0, 0, 1, 1]
        before = metrics(labels, [0.1, 0.7, 0.6, 0.9])
        after = metrics(labels, [0.51, 0.52, 0.8, 0.9])
        self.assertLess(after["eer"], before["eer"])
        self.assertGreater(after["false_positive"], before["false_positive"])

    def test_invalid_and_one_class(self):
        for labels, scores in (([0], [0.2]), ([0, 1], [0.2, float("nan")]),
                               ([0, 1], [-0.1, 0.9]), ([0, 1], [0.2])):
            with self.assertRaises(ValueError):
                metrics(labels, scores)

    def test_paired_views_reject_duplicates_missing_or_inconsistent_labels(self):
        raw = json.loads((ROOT / "evidence/frozen/results.json").read_text(encoding="utf-8"))["rows"]
        for rows in (raw[:-1], raw + [raw[0]], [dict(r, label=1-r["label"]) if i == 0 else r for i, r in enumerate(raw)]):
            with self.assertRaises(ValueError):
                summarize_rows(rows)

    def test_all_historical_metrics_reproduce(self):
        report = audit_evidence(ROOT / "evidence")
        self.assertEqual(report["originals"], 64)
        self.assertEqual(report["metrics"]["original"]["false_positive"], 28)
        self.assertEqual(report["metrics"]["predeclared_mean_original_0p8_1p25"]["eer"], 0.15625)

    def test_corrupted_evidence_is_rejected(self):
        destination = ROOT / "runs" / ("tamper-test-" + uuid.uuid4().hex)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(ROOT / "evidence", destination)
            with (destination / "frozen/results.json").open("ab") as stream:
                stream.write(b"\n ")
            with self.assertRaises(ValueError):
                audit_evidence(destination)
        finally:
            # This folder is created only by this test and must stay inside runs/.
            if not destination.resolve().is_relative_to((ROOT / "runs").resolve()):
                raise ValueError("Refusing cleanup outside test outputs")
            if destination.exists():
                shutil.rmtree(destination)


class PatternTests(unittest.TestCase):
    def test_known_repetition_differs_from_noise(self):
        rng = np.random.default_rng(42)
        t = np.arange(8000) / 16000
        motif = (0.1 + 0.4 * np.sin(2*np.pi*2*t)**2) * np.sin(2*np.pi*(180*t+380*t*t))
        repeated = np.tile(motif.astype(np.float32), 12)
        noise = rng.normal(0, 0.25, len(repeated)).astype(np.float32)
        self.assertGreater(features(repeated, 1.0)["log_rms_acf_max"],
                           features(noise, 1.0)["log_rms_acf_max"] + 0.15)


class TempoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = os.environ.get("VOICE_PROBE_FFMPEG") or shutil.which("ffmpeg")
        if not location:
            raise unittest.SkipTest("FFmpeg unavailable; tempo integration requires FFmpeg")
        cls.executable = resolve_ffmpeg(location)

    def test_pitch_duration_and_artifact_control(self):
        t = np.arange(96000) / 16000
        wave = (0.2 * np.sin(2*np.pi*440*t)).astype(np.float32)
        views = paired_views(wave, self.executable)
        self.assertEqual(set(views), {"original", "0.8", "1.0", "1.25"})
        for name, audio in views.items():
            rate = 1 if name == "original" else float(name)
            self.assertLess(abs(len(audio)/16000 - 6/rate), 0.1)
            middle = audio[3000:-3000].astype(np.float64)
            hz = np.fft.rfftfreq(len(middle), 1/16000)[np.argmax(np.abs(np.fft.rfft(middle)))]
            self.assertLess(abs(hz-440), 1)

    def test_mean_excludes_one_times_control(self):
        class RecordingBackend:
            scores = iter([0.1, 0.4, 0.99, 0.7])
            def score(self, _wave):
                return next(self.scores), 1
        wave = np.zeros(96000, dtype=np.float32)
        result = probe(wave, RecordingBackend(), self.executable)
        self.assertAlmostEqual(result["mean_score"], 0.4)
        self.assertEqual(len(result["views"]), 4)
        self.assertIsNone(result["decision"])
        self.assertFalse(result["breath_detector"])


if __name__ == "__main__":
    unittest.main()
