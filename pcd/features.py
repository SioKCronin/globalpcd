"""
pcd.features
------------
Spectral feature extraction from passive cavitation detection signals.

Extracts:
  - Subharmonic amplitude       (stable cavitation marker)
  - Ultraharmonic amplitude     (stable cavitation marker)
  - Harmonic amplitudes         (driven oscillation)
  - Broadband noise level       (inertial cavitation marker)
  - Cavitation index (CI)       (ratio: broadband / harmonic)
  - Inertial cavitation dose proxy (ICD)
  - Stable cavitation dose proxy   (SCD)

Context (free papers)
---------------------
Subharmonic / ultraharmonic vs broadband markers, and dose-style
integrals, are standard PCD practice. Open background:
https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4526372/
https://arxiv.org/abs/2601.07356
"""

import numpy as np
from dataclasses import dataclass


@dataclass
class SpectralFeatures:
    """Container for extracted PCD spectral features."""
    f_drive: float              # Drive frequency (Hz)

    subharmonic_amp: float      # Peak amplitude at f/2
    ultraharmonic_amp: float    # Peak amplitude at 3f/2
    harmonic_amps: list[float]  # Amplitudes at f, 2f, 3f
    broadband_level: float      # RMS of broadband noise floor

    # Derived metrics
    cavitation_index: float     # broadband_level / harmonic_mean — inertial proxy
    scd: float                  # Stable cavitation dose proxy (subharmonic energy)
    icd: float                  # Inertial cavitation dose proxy (broadband energy)

    # Full spectrum for plotting
    freqs: np.ndarray
    psd: np.ndarray             # Power spectral density (dB)


def active_burst_window(
    signal: np.ndarray,
    threshold_ratio: float = 0.15,
    pad_fraction: float = 0.02,
    min_fraction: float = 0.15,
) -> tuple[int, int]:
    """
    Sample span ``[start, end)`` covering the main RF energy.

    Array-simulated frames only fill a fraction of the receive buffer
    (TOF-aligned source burst). Estimating broadband / CI over the full
    buffer dilutes inertial markers; windowing to the active burst keeps
    features calibrated against direct ``generate_signal`` paths.

    If no clear burst is found (e.g. noise-only), returns the full buffer.
    """
    n = int(signal.shape[0])
    if n == 0:
        return 0, 0

    env = np.abs(np.asarray(signal, dtype=float))
    peak = float(np.max(env))
    if peak <= 0.0:
        return 0, n

    idx = np.flatnonzero(env >= threshold_ratio * peak)
    if idx.size == 0:
        return 0, n

    start = int(idx[0])
    end = int(idx[-1]) + 1
    if (end - start) < min_fraction * n:
        return 0, n

    pad = int(pad_fraction * n)
    return max(0, start - pad), min(n, end + pad)


def extract_features(
    t: np.ndarray,
    signal: np.ndarray,
    f_drive: float = 1.0e6,
    n_harmonics: int = 3,
    bin_width_hz: float = 20e3,
) -> SpectralFeatures:
    """
    Compute spectral features from a PCD time-domain signal.

    Parameters
    ----------
    t : np.ndarray
        Time axis (seconds).
    signal : np.ndarray
        RF signal samples.
    f_drive : float
        Therapy drive frequency in Hz.
    n_harmonics : int
        Number of harmonics to extract above fundamental.
    bin_width_hz : float
        Half-width of frequency bin used for peak extraction (Hz).

    Returns
    -------
    SpectralFeatures
    """
    fs = 1.0 / (t[1] - t[0])
    n = len(signal)

    # Windowed FFT
    window = np.hanning(n)
    spectrum = np.fft.rfft(signal * window)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    # Power spectral density in dB
    psd = 20 * np.log10(np.abs(spectrum) / n + 1e-12)

    def peak_in_band(f_center: float) -> float:
        """Extract peak magnitude in a narrow band around f_center."""
        mask = (freqs >= f_center - bin_width_hz) & (freqs <= f_center + bin_width_hz)
        if not np.any(mask):
            return 0.0
        return float(np.max(np.abs(spectrum[mask])) / n)

    # Subharmonic and ultraharmonic
    subharmonic_amp = peak_in_band(f_drive / 2)
    ultraharmonic_amp = peak_in_band(3 * f_drive / 2)

    # Harmonics
    harmonic_amps = [peak_in_band(k * f_drive) for k in range(1, n_harmonics + 1)]

    # Broadband noise: exclude narrow bands around harmonics and sub/ultraharmonics
    harmonic_freqs = [f_drive / 2] + [k * f_drive for k in range(1, n_harmonics + 1)] + [3 * f_drive / 2]
    broadband_mask = np.ones(len(freqs), dtype=bool)
    for hf in harmonic_freqs:
        notch = (freqs >= hf - bin_width_hz * 3) & (freqs <= hf + bin_width_hz * 3)
        broadband_mask &= ~notch

    # Also restrict to meaningful band: 0.1 MHz to 0.45 * fs
    broadband_mask &= (freqs >= 0.1e6) & (freqs <= 0.45 * fs)

    broadband_amps = np.abs(spectrum[broadband_mask]) / n
    broadband_level = float(np.sqrt(np.mean(broadband_amps ** 2))) if broadband_amps.size > 0 else 0.0

    # Cavitation index: broadband / mean harmonic
    mean_harmonic = float(np.mean(harmonic_amps)) if harmonic_amps else 1e-12
    cavitation_index = broadband_level / (mean_harmonic + 1e-12)

    # Dose proxies (energy-based)
    scd = subharmonic_amp ** 2
    icd = broadband_level ** 2

    return SpectralFeatures(
        f_drive=f_drive,
        subharmonic_amp=subharmonic_amp,
        ultraharmonic_amp=ultraharmonic_amp,
        harmonic_amps=harmonic_amps,
        broadband_level=broadband_level,
        cavitation_index=cavitation_index,
        scd=scd,
        icd=icd,
        freqs=freqs,
        psd=psd,
    )
