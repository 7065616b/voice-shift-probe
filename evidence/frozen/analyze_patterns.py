"""Fixed, label-blind temporal pattern probe on full-length speed variants.

No breath detector or deepfake classifier is fitted here. The metrics describe
repetition within one recording, then paired changes when that same recording
is played at different pitch-preserving speeds.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from scipy.io import wavfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "prep_manifest.json"
SUMMARY = HERE / "pattern_summary.json"
CHECKS = HERE / "pattern_checks.json"
CSV = HERE / "pattern_features.csv"
FFMPEG = ROOT / "work/speed_probe_v1/ffmpeg.exe"

SR = 16_000
FRAME = 400               # 25 ms
HOP = 160                 # 10 ms
NFFT = 1024
BAND_COUNT = 24
BAND_EDGES = np.geomspace(100.0, 7600.0, BAND_COUNT + 1)
ORIGINAL_LAGS = np.arange(25, 201, dtype=np.float64) * (HOP / SR)  # 0.25..2.00 s
RATES = ("original", "1.0", "0.8", "1.25")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_variant(item: dict) -> np.ndarray:
    path = ROOT / item["path"]
    if digest(path) != item["sha256"]:
        raise AssertionError(f"Audio hash changed: {path}")
    sample_rate, audio = wavfile.read(path)
    if sample_rate != SR or audio.dtype != np.float32 or len(audio) != item["samples"] or not np.isfinite(audio).all():
        raise AssertionError(f"Bad audio: {path}")
    return audio


def frontend(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Log amplitude envelope and 24-dimensional log spectral shape."""
    if len(audio) < FRAME:
        raise ValueError("Input shorter than 25 ms")
    frames = np.lib.stride_tricks.sliding_window_view(audio, FRAME)[::HOP]
    frames64 = frames.astype(np.float64)
    log_rms = np.log(np.maximum(np.sqrt(np.mean(frames64 * frames64, axis=1)), 1e-6))
    spectrum = np.abs(np.fft.rfft(frames64 * np.hanning(FRAME), n=NFFT, axis=1)) ** 2
    hz = np.fft.rfftfreq(NFFT, 1 / SR)
    band_power = np.empty((len(frames), BAND_COUNT), dtype=np.float64)
    for band in range(BAND_COUNT):
        lower, upper = BAND_EDGES[band : band + 2]
        bins = (hz >= lower) & (hz < upper)
        if not np.any(bins):
            raise AssertionError("Empty fixed frequency band")
        band_power[:, band] = np.sum(spectrum[:, bins], axis=1)
    # Relative spectral shape: global gain changes cannot create band repetition.
    relative = (band_power + 1e-8) / (np.sum(band_power, axis=1, keepdims=True) + BAND_COUNT * 1e-8)
    return log_rms[:, None], np.log(relative)


def normalized_acf(series: np.ndarray) -> np.ndarray:
    """Overlap-normalized, globally centered lag cosine summed over bands.

    z[t,b]=(series[t,b]-mean_b)/max(sd_b,0.001). At lag k, the numerator is
    sum_{t=0}^{N-k-1,b} z[t,b] z[t+k,b] and the denominator is the geometric
    mean of the two overlapping segments' squared norms. FFT computes all
    numerator lags; cumulative energy computes each denominator exactly.
    """
    if series.ndim != 2:
        raise ValueError("Expected [frames,bands]")
    n = len(series)
    z = series - np.mean(series, axis=0, keepdims=True)
    z = z / np.maximum(np.std(z, axis=0, keepdims=True), 1e-3)
    fft_size = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(z, n=fft_size, axis=0)
    numerators = np.fft.irfft(np.sum(f.real * f.real + f.imag * f.imag, axis=1), n=fft_size)[:n]
    power = np.sum(z * z, axis=1)
    prefix = np.concatenate(([0.0], np.cumsum(power)))
    lags = np.arange(n)
    energy_left = prefix[n - lags]
    energy_right = prefix[n] - prefix[lags]
    denom = np.sqrt(np.maximum(energy_left * energy_right, 0.0))
    acf = np.divide(numerators, denom, out=np.zeros(n, dtype=np.float64), where=denom > 1e-12)
    return np.clip(acf, -1.0, 1.0)


def features(audio: np.ndarray, rate: float) -> dict:
    envelope, spectrum = frontend(audio)
    result = {"frame_count": int(len(envelope))}
    for name, stream in (("log_rms", envelope), ("log_spectral_shape", spectrum)):
        acf = normalized_acf(stream)
        output_lags_in_frames = ORIGINAL_LAGS / (rate * HOP / SR)
        if output_lags_in_frames[-1] >= len(acf) - 1:
            raise ValueError("Too short to evaluate fixed original-time lags")
        values = np.interp(output_lags_in_frames, np.arange(len(acf)), acf)
        best = int(np.argmax(values))
        result[f"{name}_acf_max"] = float(values[best])
        result[f"{name}_acf_median"] = float(np.median(values))
        result[f"{name}_acf_contrast"] = float(values[best] - np.median(values))
        result[f"{name}_peak_lag_original_seconds"] = float(ORIGINAL_LAGS[best])
    return result


def atempo(audio: np.ndarray, rate: float) -> np.ndarray:
    # Synthetic control only; real inputs are the frozen prepared WAV files.
    result = subprocess.run(
        [str(FFMPEG), "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
         "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0", "-vn",
         "-af", f"atempo={rate:g}", "-f", "f32le", "pipe:1"],
        input=np.asarray(audio, dtype="<f4").tobytes(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode or len(result.stdout) % 4:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-1000:])
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def synthetic_checks() -> dict:
    rng = np.random.default_rng(236749)
    period = 0.5
    t = np.arange(round(SR * period), dtype=np.float64) / SR
    amplitude = 0.10 + 0.55 * np.sin(2 * np.pi * 2 * t) ** 2
    motif = amplitude * (0.7 * np.sin(2 * np.pi * (180 * t + 380 * t * t)) +
                         0.3 * np.sin(2 * np.pi * (900 * t + 250 * t * t)))
    repeated = np.tile(motif.astype(np.float32), 12)
    random = (rng.normal(0, 0.25, len(repeated))).astype(np.float32)
    same_first = features(repeated, 1.0)
    same_second = features(repeated.copy(), 1.0)
    same_input_equal = same_first == same_second
    controls = {}
    for key, rate in (("0.8", 0.8), ("1.0", 1.0), ("1.25", 1.25)):
        repeated_audio = atempo(repeated, rate)
        random_audio = atempo(random, rate)
        repeated_result = features(repeated_audio, rate)
        random_result = features(random_audio, rate)
        for name, index in (("log_rms", 0), ("log_spectral_shape", 1)):
            repeated_stream = frontend(repeated_audio)[index]
            random_stream = frontend(random_audio)[index]
            physical_frame_lag = period / (rate * HOP / SR)
            repeated_result[f"{name}_acf_at_original_0p5s"] = float(np.interp(
                physical_frame_lag, np.arange(len(repeated_stream)), normalized_acf(repeated_stream)))
            random_result[f"{name}_acf_at_original_0p5s"] = float(np.interp(
                physical_frame_lag, np.arange(len(random_stream)), normalized_acf(random_stream)))
        for name in ("log_rms", "log_spectral_shape"):
            repeated_result[f"{name}_excess_vs_random"] = (
                repeated_result[f"{name}_acf_max"] - random_result[f"{name}_acf_max"]
            )
        controls[key] = {"repeated": repeated_result, "random": random_result}
    criteria = {
        "same_signal_reanalysis_exact": same_input_equal,
        "repeated_envelope_exceeds_random_at_all_rates_by_0p15": all(
            item["repeated"]["log_rms_excess_vs_random"] > 0.15 for item in controls.values()),
        "repeated_spectrum_exceeds_random_at_all_rates_by_0p15": all(
            item["repeated"]["log_spectral_shape_excess_vs_random"] > 0.15 for item in controls.values()),
        "repeated_0p5s_lag_remains_strong_at_all_rates": all(
            item["repeated"][f"{name}_acf_at_original_0p5s"] > 0.7 and
            item["repeated"][f"{name}_acf_at_original_0p5s"] -
            item["random"][f"{name}_acf_at_original_0p5s"] > 0.3
            for item in controls.values() for name in ("log_rms", "log_spectral_shape")),
        "maximum_lag_is_a_half_second_multiple_at_all_rates": all(
            min(abs(item["repeated"][f"{name}_peak_lag_original_seconds"] - multiple * period)
                for multiple in (1, 2, 3, 4)) <= 0.08
            for item in controls.values() for name in ("log_rms", "log_spectral_shape")),
    }
    return {"synthetic_period_seconds": period, "controls": controls,
            "criteria": criteria, "passed": all(criteria.values())}


def summary_stat(values: list[float]) -> dict:
    v = np.asarray(values, dtype=np.float64)
    return {"median": float(np.median(v)), "q25": float(np.quantile(v, 0.25)),
            "q75": float(np.quantile(v, 0.75)), "min": float(v.min()), "max": float(v.max())}


def main() -> None:
    if CSV.exists() or SUMMARY.exists() or CHECKS.exists():
        raise FileExistsError("Pattern probe already has outputs; preserve the frozen result")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["source_count"] != 64 or manifest["violations"]:
        raise AssertionError("Prepared audio is not the expected 64 clean source pairs")
    records = []
    for index, item in enumerate(manifest["rows"], 1):
        source = item["variants"]
        by_rate = {}
        for key in RATES:
            rate = 1.0 if key == "original" else float(key)
            feats = features(read_variant(source[key]), rate)
            by_rate[key] = feats
        for key in RATES:
            row = {"id": item["id"], "label": item["label"], "generator": item["generator"],
                   "rate": key, "source_seconds": item["source_decoded"]["seconds"],
                   "variant_seconds": source[key]["seconds"], **by_rate[key]}
            for name in ("log_rms", "log_spectral_shape"):
                for metric in ("acf_max", "acf_median", "acf_contrast"):
                    col = f"{name}_{metric}"
                    row[f"{col}_delta_from_original"] = by_rate[key][col] - by_rate["original"][col]
            records.append(row)
        print(f"PATTERN {index}/64 {item['id']}", flush=True)
    with CSV.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    groups = {}
    for generator in ("human", "f5tts", "yourtts"):
        subset = [row for row in records if row["generator"] == generator]
        groups[generator] = {"source_count": len(subset) // 4, "rates": {}}
        for key in RATES:
            group = [row for row in subset if row["rate"] == key]
            groups[generator]["rates"][key] = {
                "n_sources": len(group),
                "source_seconds": summary_stat([row["source_seconds"] for row in group]),
                **{col: summary_stat([row[col] for row in group]) for name in ("log_rms", "log_spectral_shape")
                   for col in (f"{name}_acf_max", f"{name}_acf_contrast",
                               f"{name}_acf_max_delta_from_original", f"{name}_acf_contrast_delta_from_original")},
            }
    summary = {
        "name": "speed_probe_v1_temporal_patterns", "status": "exploratory_complete",
        "manifest_sha256": digest(MANIFEST), "features_sha256": digest(CSV),
        "source_count": 64, "derived_record_count": len(records),
        "known_labels_used_only_for_group_summary": True,
        "settings": {
            "sample_rate_hz": SR, "frame_samples": FRAME, "hop_samples": HOP,
            "window": "numpy.hanning(400)", "fft_size": NFFT,
            "log_rms": "ln(max(sqrt(mean(frame^2)),1e-6))",
            "spectral_shape": "ln((band_power+1e-8)/(sum_band_power+24e-8))",
            "bands": BAND_COUNT, "band_edges_hz": BAND_EDGES.tolist(),
            "acf": "For each band globally center and divide by max(std,0.001); at output-frame lag k, sum_t,b z[t,b]z[t+k,b]/sqrt(sum_t,b z[t,b]^2 * sum_t,b z[t+k,b]^2), using matching overlap ranges; clip [-1,1]",
            "original_lags_seconds": {"first": float(ORIGINAL_LAGS[0]), "last": float(ORIGINAL_LAGS[-1]),
                                       "step": HOP / SR, "count": len(ORIGINAL_LAGS)},
            "time_normalization": "For original lag tau and speed r, sample the processed ACF at tau/(r*0.01s) frames by linear interpolation; summarize on the same 176 original-time lags for every r.",
            "summaries": ["maximum", "median", "max_minus_median", "original_time_of_maximum"],
            "normalization": "No loudness normalization, equal-length crop, breath labeling, model-score fitting, or threshold training",
        },
        "groups": groups,
        "limitations": ["Previously observed 64 recordings from one corpus/generator families; speaker independence unverified",
                        "Within-file self-similarity is not uniquely human or AI", "Speed transformation may create processing artifacts",
                        "Recording length and source differences can affect absolute group summaries",
                        "No breath event annotation, deepfake detector score, EER, ADS, or official submission"],
    }
    checks = synthetic_checks()
    checks.update({
        "manifest_sha256": digest(MANIFEST), "features_sha256": digest(CSV),
        "source_pairing_exact": len(records) == 256 and len({row["id"] for row in records}) == 64 and all(
            sum(row["id"] == item["id"] for row in records) == 4 for item in manifest["rows"]),
        "all_numeric_features_finite": all(
            math.isfinite(float(value)) for row in records for key, value in row.items()
            if key not in ("id", "generator", "rate")),
    })
    checks["passed"] = checks["passed"] and checks["source_pairing_exact"] and checks["all_numeric_features_finite"]
    save_json(SUMMARY, summary)
    save_json(CHECKS, checks)
    print(json.dumps({"source_count": 64, "rows": len(records), "checks_passed": checks["passed"],
                      "criteria": checks["criteria"]}, ensure_ascii=False), flush=True)
    if not checks["passed"]:
        raise AssertionError("Control check failed; inspect pattern_checks.json")


if __name__ == "__main__":
    main()
