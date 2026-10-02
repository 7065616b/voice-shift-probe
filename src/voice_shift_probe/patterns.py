"""Label-blind temporal features from the archived probe; not a breath detector."""
import numpy as np
SR = 16000
FRAME = 400
HOP = 160
NFFT = 1024
BAND_COUNT = 24
BAND_EDGES = np.geomspace(100.0, 7600.0, BAND_COUNT + 1)
ORIGINAL_LAGS = np.arange(25, 201, dtype=np.float64) * (HOP / SR)

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
