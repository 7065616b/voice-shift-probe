"""Cross-platform FFmpeg decoding and pitch-preserving paired interventions."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np

SR = 16000


def resolve_ffmpeg(path=None):
    executable = str(path) if path else shutil.which("ffmpeg")
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError("Install FFmpeg or provide --ffmpeg /path/to/ffmpeg")
    return executable


def run_f32(executable, arguments, payload=None):
    completed = subprocess.run(
        [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", *arguments],
        input=payload, capture_output=True, check=False,
    )
    if completed.returncode or len(completed.stdout) % 4:
        raise RuntimeError("FFmpeg failed: " + completed.stderr.decode("utf-8", "replace")[-1000:])
    wave = np.frombuffer(completed.stdout, dtype="<f4").copy()
    if not wave.size or not np.isfinite(wave).all():
        raise ValueError("Empty or nonfinite audio")
    return wave


def decode(path, executable):
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    return run_f32(executable, ["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"])


def atempo(wave, rate, executable):
    if rate not in (0.8, 1.0, 1.25):
        raise ValueError("This protocol fixes tempo factors to 0.8, 1.0, 1.25")
    if wave.ndim != 1 or wave.size < 4096 or not np.isfinite(wave).all():
        raise ValueError("Tempo input must be finite mono audio with at least 4096 samples")
    return run_f32(executable,
        ["-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0", "-vn",
         "-af", f"atempo={rate:g}", "-f", "f32le", "pipe:1"],
        np.asarray(wave, dtype="<f4").tobytes())


def paired_views(wave, executable):
    # Even 1.0 passes through atempo: this is the transformation-artifact control.
    return {"original": wave.copy(), **{str(r): atempo(wave, r, executable) for r in (0.8, 1.0, 1.25)}}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pcm_hash(wave):
    return hashlib.sha256(np.asarray(wave, dtype="<f4").tobytes()).hexdigest()
