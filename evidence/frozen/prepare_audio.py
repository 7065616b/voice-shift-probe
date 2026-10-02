"""Prepare paired, full-length pitch-preserving speed variants for an audit.

The 64 source recordings and their labels were selected before this script.
This script does not score or train a detector. It keeps the full source audio,
and the same FFmpeg decoding path is used for every source and rate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FFMPEG = ROOT / "work/speed_probe_v1/ffmpeg.exe"
INPUT_MANIFEST = ROOT / "outputs/energy_pool_v1/inputs_manifest.json"
OUT = ROOT / "work/speed_probe_v1/audio"
PREP_MANIFEST = HERE / "prep_manifest.json"
PREP_SANITY = HERE / "prep_sanity.json"
SAMPLE_RATE = 16_000
RATES = (("0.8", 0.8), ("1.0", 1.0), ("1.25", 1.25))
EXPECTED_FFMPEG_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def ffmpeg_f32(command: list[str], payload: bytes | None = None) -> np.ndarray:
    result = subprocess.run(
        [str(FFMPEG), "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", *command],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode or len(result.stdout) % 4:
        raise RuntimeError(f"FFmpeg failed ({result.returncode}): {result.stderr.decode('utf-8', 'replace')[-1000:]}")
    audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Empty or nonfinite FFmpeg output")
    return audio


def decode_source(path: Path) -> np.ndarray:
    return ffmpeg_f32(["-i", str(path), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"])


def change_speed(audio: np.ndarray, rate: float) -> np.ndarray:
    return ffmpeg_f32(
        ["-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-vn", "-af", f"atempo={rate:g}", "-f", "f32le", "pipe:1"],
        np.asarray(audio, dtype="<f4").tobytes(),
    )


def describe(audio: np.ndarray) -> dict:
    peak = float(np.max(np.abs(audio)))
    return {
        "samples": int(len(audio)),
        "seconds": float(len(audio) / SAMPLE_RATE),
        "peak": peak,
        "rms": float(np.sqrt(np.mean(np.square(audio.astype(np.float64))))),
        "finite": bool(np.isfinite(audio).all()),
        "within_float_audio_range": bool(peak < 1.0),
        "exact_full_scale_samples": int(np.count_nonzero(np.abs(audio) >= 1.0)),
    }


def save_wav(path: Path, audio: np.ndarray) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, SAMPLE_RATE, audio.astype(np.float32, copy=False))
    stored_sr, stored = wavfile.read(path)
    if stored_sr != SAMPLE_RATE or stored.dtype != np.float32 or not np.array_equal(stored, audio):
        raise AssertionError(f"WAV round trip changed the samples: {path}")
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), **describe(audio)}


def dominant_frequency(audio: np.ndarray, skip: int = 3_000) -> float:
    # FFT over a middle segment avoids most tempo-filter edge transients.
    x = audio[skip:-skip] if len(audio) > 2 * skip + 1024 else audio
    x = x.astype(np.float64)
    x -= x.mean()
    fft = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    frequency = np.fft.rfftfreq(len(x), 1 / SAMPLE_RATE)
    return float(frequency[int(np.argmax(fft))])


def controls() -> dict:
    t = np.arange(SAMPLE_RATE * 5, dtype=np.float64) / SAMPLE_RATE
    sine = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    # Silence-bracketed transient checks event timing independently of pitch.
    impulse = np.zeros_like(sine)
    impulse[SAMPLE_RATE] = 0.5
    impulse[3 * SAMPLE_RATE] = 0.5
    results = {}
    for rate_key, rate in RATES:
        tone = change_speed(sine, rate)
        transient = change_speed(impulse, rate)
        expected_duration = len(sine) / SAMPLE_RATE / rate
        duration_error = abs(len(tone) / SAMPLE_RATE - expected_duration)
        frequency = dominant_frequency(tone)
        transient_events = []
        for original_seconds in (1.0, 3.0):
            expected_seconds = original_seconds / rate
            left = max(0, round((expected_seconds - 0.12) * SAMPLE_RATE))
            right = min(len(transient), round((expected_seconds + 0.12) * SAMPLE_RATE))
            peak_position = left + int(np.argmax(np.abs(transient[left:right])))
            observed_seconds = peak_position / SAMPLE_RATE
            transient_events.append({
                "original_seconds": original_seconds,
                "expected_seconds": expected_seconds,
                "observed_seconds": observed_seconds,
                "error_seconds": abs(observed_seconds - expected_seconds),
                "peak": float(abs(transient[peak_position])),
            })
        results[rate_key] = {
            "tone_seconds": len(tone) / SAMPLE_RATE,
            "expected_seconds": expected_duration,
            "tone_duration_error_seconds": duration_error,
            "dominant_frequency_hz": frequency,
            "tone_frequency_error_hz": abs(frequency - 440.0),
            "impulse_seconds": len(transient) / SAMPLE_RATE,
            "impulse_peak": float(np.max(np.abs(transient))),
            "transient_events": transient_events,
            "max_transient_timing_error_seconds": max(x["error_seconds"] for x in transient_events),
            "within_transient_timing_tolerance_50ms": all(x["error_seconds"] <= 0.05 for x in transient_events),
            "within_duration_tolerance": duration_error <= max(0.08, 0.02 * expected_duration),
            "within_pitch_tolerance_5hz": abs(frequency - 440.0) < 5.0,
            "finite": bool(np.isfinite(tone).all() and np.isfinite(transient).all()),
            "rate1_sample_equal_to_input": bool(np.array_equal(tone, sine)) if rate == 1.0 else None,
        }
    return results


def main() -> None:
    if not FFMPEG.is_file() or sha256(FFMPEG) != EXPECTED_FFMPEG_SHA256:
        raise RuntimeError("FFmpeg executable missing or SHA256 changed")
    prior = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    samples = prior["samples"]
    if len(samples) != 64 or len({row["id"] for row in samples}) != 64:
        raise AssertionError("Expected 64 unique, fixed source IDs")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", row["id"]) for row in samples):
        raise AssertionError("Unexpected source ID")
    if PREP_MANIFEST.exists() or PREP_SANITY.exists():
        raise FileExistsError("Preparation already has a receipt; preserve it")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    errors = []
    for index, row in enumerate(samples, 1):
        source = ROOT / row["source_path"]
        if not source.is_file() or sha256(source) != row["source_sha256"]:
            raise AssertionError(f"Source absent or hash changed: {row['id']}")
        original = decode_source(source)
        base = describe(original)
        outputs = {}
        outputs["original"] = save_wav(OUT / f"{row['id']}__original.wav", original)
        for rate_key, rate in RATES:
            processed = change_speed(original, rate)
            item = save_wav(OUT / f"{row['id']}__atempo_{rate_key.replace('.', 'p')}.wav", processed)
            target = base["seconds"] / rate
            item["expected_seconds"] = target
            item["duration_error_seconds"] = abs(item["seconds"] - target)
            item["duration_tolerance_seconds"] = max(0.08, 0.02 * target)
            item["within_duration_tolerance"] = item["duration_error_seconds"] <= item["duration_tolerance_seconds"]
            item["sample_equal_to_original"] = bool(np.array_equal(processed, original)) if rate == 1.0 else None
            outputs[rate_key] = item
            if not item["within_duration_tolerance"]:
                errors.append({"id": row["id"], "rate": rate_key, "reason": "duration_outside_tolerance", "error_seconds": item["duration_error_seconds"]})
            if not item["within_float_audio_range"]:
                errors.append({"id": row["id"], "rate": rate_key, "reason": "reaches_or_exceeds_full_scale", "peak": item["peak"]})
        if not base["within_float_audio_range"]:
            errors.append({"id": row["id"], "rate": "original", "reason": "source_reaches_or_exceeds_full_scale", "peak": base["peak"]})
        rows.append({
            "id": row["id"], "label": row["label"], "generator": row["generator"],
            "source_path": row["source_path"], "source_sha256": row["source_sha256"],
            "source_original_seconds_manifest": row["original_seconds"],
            "source_decoded": base, "variants": outputs,
        })
        print(f"PREPARED {index}/64 {row['id']}", flush=True)
    sanity = controls()
    manifest = {
        "name": "full_audio_speed_probe_v1", "status": "passed" if not errors else "completed_with_violations",
        "input_manifest_path": INPUT_MANIFEST.relative_to(ROOT).as_posix(),
        "input_manifest_sha256": sha256(INPUT_MANIFEST),
        "ffmpeg_path": FFMPEG.relative_to(ROOT).as_posix(), "ffmpeg_sha256": sha256(FFMPEG),
        "sample_rate": SAMPLE_RATE, "channels": 1, "wav_encoding": "IEEE_FLOAT32",
        "process": "decode full FLAC through FFmpeg to mono 16k float32; apply FFmpeg atempo to the same decoded waveform, including rate 1.0; no crop, gain normalization or clipping",
        "rates": [rate for _, rate in RATES], "source_count": len(rows),
        "independent_original_count": len(rows), "variant_count": len(rows) * (len(RATES) + 1),
        "duration_tolerance_rule": "max(0.08s, 0.02 * expected duration)",
        "rows": rows, "violations": errors,
    }
    write_json(PREP_MANIFEST, manifest)
    check = {
        "name": "full_audio_speed_probe_v1_sanity",
        "manifest_sha256": sha256(PREP_MANIFEST),
        "ffmpeg_sha256": sha256(FFMPEG),
        "known_sine_440hz_and_impulse_controls": sanity,
        "all_control_duration_and_pitch_checks_passed": all(v["within_duration_tolerance"] and v["within_pitch_tolerance_5hz"] and v["within_transient_timing_tolerance_50ms"] and v["finite"] for v in sanity.values()),
        "all_audio_duration_and_float_range_checks_passed": not errors,
        "rate1_identical_to_decoded_count": sum(row["variants"]["1.0"]["sample_equal_to_original"] for row in rows),
        "source_count": len(rows), "violation_count": len(errors),
    }
    write_json(PREP_SANITY, check)
    print(json.dumps({k: v for k, v in check.items() if k != "known_sine_440hz_and_impulse_controls"}, ensure_ascii=False), flush=True)
    if not check["all_control_duration_and_pitch_checks_passed"] or errors:
        raise AssertionError("Preparation completed with failed checks; inspect prep_sanity.json")


if __name__ == "__main__":
    main()
