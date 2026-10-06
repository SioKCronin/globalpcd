"""
pcd.signals
-----------
Synthetic passive cavitation detection signal generator.

Produces time-domain RF signals mimicking the acoustic emissions
received by a passive transducer during histotripsy treatment.

Three cavitation regimes:
  - none:     background noise only
  - stable:   harmonics + subharmonic (f/2) + ultraharmonics (3f/2)
  - inertial: broadband noise elevation (wideband collapse signature)

Context (free papers)
---------------------
These regimes are didactic synthetics, not measured RF. Open
background on what real PCD emissions look like:
https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4526372/
https://arxiv.org/abs/2512.22292
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np

CavitationRegime = Literal["none", "stable", "inertial"]


@dataclass
class SignalParams:
    """Parameters for synthetic PCD signal generation."""
    fs: float = 100e6          # Sample rate (Hz)
    duration: float = 50e-6   # Signal window duration (s)
    f_drive: float = 1.0e6    # Therapy drive frequency (Hz)
    snr_db: float = 20.0      # Signal-to-noise ratio (dB)

    # Stable cavitation amplitudes (relative)
    harmonic_amp: float = 0.5
    subharmonic_amp: float = 0.3      # f/2  — key stable cavitation marker
    ultraharmonic_amp: float = 0.15   # 3f/2

    # Inertial cavitation: broadband noise boost (dB above floor)
    broadband_boost_db: float = 25.0

    # Inertial cavitation: fraction of spectrum filled with coherent burst
    broadband_fraction: float = 0.7

    seed: int = 42

    @classmethod
    def lifu(
        cls,
        f_drive: float = 500e3,
        **overrides: Any,
    ) -> "SignalParams":
        """
        Synthetic preset in the OpenLIFU neuromodulation band.

        Drive is 200–650 kHz (default 500 kHz), with a longer window and
        lower sample rate than the histotripsy defaults. This is for
        controller-facing tests, not a claim about real LIFU emissions.
        """
        if not (200e3 <= f_drive <= 650e3):
            raise ValueError(
                f"LIFU preset f_drive must be in 200–650 kHz, got {f_drive}"
            )
        params = cls(
            fs=10e6,
            duration=200e-6,
            f_drive=f_drive,
            snr_db=20.0,
        )
        for key, value in overrides.items():
            if not hasattr(params, key):
                raise TypeError(f"unknown SignalParams field: {key}")
            setattr(params, key, value)
        return params


def generate_signal(
    regime: CavitationRegime,
    params: SignalParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate a synthetic PCD time-domain signal.

    Parameters
    ----------
    regime : CavitationRegime
        One of 'none', 'stable', 'inertial'.
    params : SignalParams, optional
        Generation parameters. Defaults to SignalParams().

    Returns
    -------
    t : np.ndarray
        Time axis (seconds).
    signal : np.ndarray
        Normalised RF signal (float64, range ≈ [-1, 1]).
    """
    if params is None:
        params = SignalParams()

    rng = np.random.default_rng(params.seed)
    n_samples = int(params.fs * params.duration)
    t = np.linspace(0, params.duration, n_samples, endpoint=False)

    noise_amplitude = 10 ** (-params.snr_db / 20)
    signal = rng.normal(0, noise_amplitude, n_samples)

    f = params.f_drive

    if regime == "none":
        pass  # pure noise

    elif regime == "stable":
        # Drive frequency and harmonics
        for harmonic in [1, 2, 3]:
            phase = rng.uniform(0, 2 * np.pi)
            amp = params.harmonic_amp / harmonic
            signal += amp * np.sin(2 * np.pi * harmonic * f * t + phase)

        # Subharmonic f/2  — hallmark of stable cavitation
        phase = rng.uniform(0, 2 * np.pi)
        signal += params.subharmonic_amp * np.sin(2 * np.pi * (f / 2) * t + phase)

        # Ultraharmonic 3f/2
        phase = rng.uniform(0, 2 * np.pi)
        signal += params.ultraharmonic_amp * np.sin(2 * np.pi * (3 * f / 2) * t + phase)

    elif regime == "inertial":
        # Broadband noise burst — wideband inertial collapse signature.
        # We build the signal directly in the frequency domain so that
        # broadband energy genuinely dominates after normalisation.
        freqs = np.fft.rfftfreq(n_samples, d=1 / params.fs)
        n_rfft = len(freqs)

        # Start from white noise in frequency domain
        phases = rng.uniform(0, 2 * np.pi, n_rfft)
        amplitudes = np.ones(n_rfft)

        # Shape: keep energy only in the therapeutic band
        f_low = 0.1e6
        f_high = params.fs * 0.45 * params.broadband_fraction
        band_mask = (freqs >= f_low) & (freqs <= f_high)
        amplitudes[~band_mask] = 0.0

        # Suppress narrow bands around harmonics so they don't look like
        # harmonic peaks — real inertial emissions have no tonal structure
        for harmonic in [0.5, 1.0, 1.5, 2.0, 3.0]:
            notch = np.abs(freqs - harmonic * f) < 30e3
            amplitudes[notch] = 0.0

        broadband_spectrum = amplitudes * np.exp(1j * phases)
        broadband = np.fft.irfft(broadband_spectrum, n=n_samples)

        # Scale so broadband RMS >> residual harmonic
        boost = 10 ** (params.broadband_boost_db / 20) * noise_amplitude
        rms = np.sqrt(np.mean(broadband ** 2)) + 1e-12
        broadband = broadband / rms * boost

        signal += broadband

        # Small residual at drive frequency (therapy transducer leakage)
        signal += 0.05 * np.sin(2 * np.pi * f * t)

    else:
        raise ValueError(f"Unknown regime: {regime!r}")

    # Normalise
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak

    return t, signal


def iter_signals(
    regimes: Sequence[CavitationRegime] | CavitationRegime,
    params: SignalParams | None = None,
    *,
    n_frames: int | None = None,
    seed_step: int = 1,
) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    """
    Stream synthetic PCD frames for feedback-layer testing (no hardware).

    Yields ``(frame_id, t, signal)`` where each frame is an independent
    window from :func:`generate_signal`. Pass a single regime to hold it
    fixed, or a sequence to cycle (e.g. ``["none", "stable", "inertial"]``).

    Parameters
    ----------
    regimes :
        One regime, or a sequence cycled across frames.
    params :
        Base generation parameters. ``seed`` advances by ``seed_step``
        each frame so successive windows are not identical.
    n_frames :
        Stop after this many frames. ``None`` yields forever.
    seed_step :
        Increment applied to ``params.seed`` per frame.
    """
    if params is None:
        params = SignalParams()

    if isinstance(regimes, str):
        cycle: Sequence[CavitationRegime] = (regimes,)
    else:
        cycle = tuple(regimes)
        if not cycle:
            raise ValueError("regimes sequence must be non-empty")

    frame_id = 0
    while n_frames is None or frame_id < n_frames:
        regime = cycle[frame_id % len(cycle)]
        frame_params = replace(params, seed=params.seed + frame_id * seed_step)
        t, signal = generate_signal(regime, frame_params)
        yield frame_id, t, signal
        frame_id += 1
