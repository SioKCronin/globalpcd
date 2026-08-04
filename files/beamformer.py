"""
pcd.beamformer
--------------
Passive acoustic source localisation using GCC-PHAT and delay-and-sum.

Two complementary algorithms are provided:

1. gcc_phat_map  (recommended)
   -------------------------
   Generalised Cross-Correlation with PHAse Transform (GCC-PHAT).
   Measures the time-difference-of-arrival (TDOA) between every element
   and a reference element using phase-weighted cross-correlation, then
   performs a grid search to find the source location that best explains
   all observed TDOAs (minimum squared TDOA residual).

   GCC-PHAT is robust to broadband signals and moderate noise — ideal for
   inertial cavitation emissions which are inherently wideband.

2. delay_and_sum  (classic, included for comparison)
   --------------------------------------------------
   Conventional passive DAS beamformer using relative TOF delays and
   coherent summation of analytic (Hilbert-transformed) signals.
   Works well for narrowband sources; contrast degrades for broadband.

Coordinate system
-----------------
   - Array face at z = 0.
   - Tissue and imaging grid at z > 0 (positive axial).
   - Lateral axis is x, symmetric about 0.

Context (free papers)
---------------------
Array-based passive cavitation mapping — open overview:
https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d
PAM beamforming on arXiv: https://arxiv.org/abs/2412.02413
Angular-spectrum PAM (open full text):
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5565398/
"""

import numpy as np
from dataclasses import dataclass
from scipy.signal import hilbert


@dataclass
class ArrayGeometry:
    """
    2D passive receive array geometry.

    element_positions : np.ndarray, shape (N, 2)
        (x, z) positions of each element in metres.
        For a standard linear array, all z = 0.
    """
    element_positions: np.ndarray

    @classmethod
    def linear(
        cls,
        n_elements: int = 16,
        pitch: float = 1.5e-3,
    ) -> "ArrayGeometry":
        """
        Create a centred linear array at z = 0.

        Parameters
        ----------
        n_elements : int
            Number of passive receive elements.
        pitch : float
            Centre-to-centre element spacing (m).
        """
        x = np.linspace(
            -(n_elements - 1) / 2,
             (n_elements - 1) / 2,
            n_elements,
        ) * pitch
        return cls(element_positions=np.column_stack([x, np.zeros(n_elements)]))


@dataclass
class PAMResult:
    """2D passive acoustic map output."""
    intensity: np.ndarray               # (n_z, n_x)  — raw scores
    intensity_db: np.ndarray            # (n_z, n_x)  — normalised dB
    x_axis: np.ndarray                  # lateral axis (m)
    z_axis: np.ndarray                  # axial axis (m)
    peak_location: tuple[float, float]  # (x, z) of peak in metres


# ---------------------------------------------------------------------------
# GCC-PHAT localisation (recommended)
# ---------------------------------------------------------------------------

def gcc_phat_map(
    signals: np.ndarray,
    fs: float,
    array: ArrayGeometry,
    x_range: tuple[float, float] = (-10e-3, 10e-3),
    z_range: tuple[float, float] = (20e-3, 60e-3),
    grid_points: int = 80,
    c: float = 1540.0,
    ref_element: int | None = None,
) -> PAMResult:
    """
    Passive source localisation via GCC-PHAT TDOA grid search.

    For each element pair (element_i, reference), GCC-PHAT estimates
    the TDOA with sub-sample precision. A grid search then finds the
    spatial point whose predicted TDOAs best fit the measurements
    (minimum sum-of-squared TDOA residuals).

    Parameters
    ----------
    signals : np.ndarray, shape (N_elements, N_samples)
    fs : float
        Sample rate (Hz).
    array : ArrayGeometry
    x_range, z_range : (float, float)
        Grid extents in metres.
    grid_points : int
        Points per axis (grid is grid_points × grid_points).
    c : float
        Speed of sound (m/s). Default 1540 (soft tissue).
    ref_element : int or None
        Index of reference element for TDOA estimation.
        Defaults to the centre element.

    Returns
    -------
    PAMResult
    """
    n_elements, n_samples = signals.shape
    assert n_elements == len(array.element_positions)

    if ref_element is None:
        ref_element = n_elements // 2

    # --- Step 1: GCC-PHAT TDOAs vs reference element ----------------------
    ref_fft = np.fft.rfft(signals[ref_element])
    measured_tdoas = np.zeros(n_elements)

    lag_axis = np.arange(-n_samples // 2, n_samples // 2) / fs

    for ie in range(n_elements):
        if ie == ref_element:
            continue
        R      = np.fft.rfft(signals[ie]) * np.conj(ref_fft)
        R_phat = R / (np.abs(R) + 1e-10)          # phase-only weighting
        cc     = np.fft.fftshift(np.fft.irfft(R_phat, n=n_samples))
        measured_tdoas[ie] = lag_axis[np.argmax(cc)]

    # --- Step 2: Grid search for best-fit source location -----------------
    x_axis    = np.linspace(x_range[0], x_range[1], grid_points)
    z_axis    = np.linspace(z_range[0], z_range[1], grid_points)
    elem_pos  = array.element_positions
    ref_pos   = elem_pos[ref_element]

    # Negative squared TDOA residual → high = good match
    intensity = np.zeros((len(z_axis), len(x_axis)))

    for iz, z in enumerate(z_axis):
        for ix, x in enumerate(x_axis):
            r = np.array([x, z])
            pred_tofs   = np.linalg.norm(elem_pos - r, axis=1) / c
            pred_tdoas  = pred_tofs - pred_tofs[ref_element]
            residuals   = pred_tdoas - measured_tdoas
            intensity[iz, ix] = -float(np.sum(residuals ** 2))

    # Shift to positive range then normalise to dB
    intensity   -= intensity.min()
    peak_val     = intensity.max()
    intensity_db = 20 * np.log10(intensity / (peak_val + 1e-12) + 1e-12)

    peak_idx      = np.unravel_index(np.argmax(intensity), intensity.shape)
    peak_location = (float(x_axis[peak_idx[1]]), float(z_axis[peak_idx[0]]))

    return PAMResult(
        intensity=intensity,
        intensity_db=intensity_db,
        x_axis=x_axis,
        z_axis=z_axis,
        peak_location=peak_location,
    )


# ---------------------------------------------------------------------------
# Classic delay-and-sum (included for comparison / education)
# ---------------------------------------------------------------------------

def delay_and_sum(
    signals: np.ndarray,
    fs: float,
    array: ArrayGeometry,
    x_range: tuple[float, float] = (-10e-3, 10e-3),
    z_range: tuple[float, float] = (20e-3, 60e-3),
    grid_points: int = 80,
    c: float = 1540.0,
) -> PAMResult:
    """
    Classic passive delay-and-sum beamformer.

    Works well for narrowband signals. For broadband inertial cavitation
    emissions, prefer gcc_phat_map() which is more robust.

    Parameters
    ----------
    signals : np.ndarray, shape (N_elements, N_samples)
    fs : float
    array : ArrayGeometry
    x_range, z_range : (float, float)
    grid_points : int
    c : float

    Returns
    -------
    PAMResult
    """
    n_elements, n_samples = signals.shape
    analytic  = hilbert(signals, axis=1)
    elem_pos  = array.element_positions

    x_axis    = np.linspace(x_range[0], x_range[1], grid_points)
    z_axis    = np.linspace(z_range[0], z_range[1], grid_points)
    intensity = np.zeros((len(z_axis), len(x_axis)))

    for iz, z in enumerate(z_axis):
        for ix, x in enumerate(x_axis):
            r            = np.array([x, z])
            tofs         = np.linalg.norm(elem_pos - r, axis=1) / c
            rel_delays   = (tofs - tofs.min()) * fs
            coherent_sum = np.zeros(n_samples, dtype=complex)

            for ie in range(n_elements):
                d    = rel_delays[ie]
                i0   = int(np.floor(d))
                frac = d - i0
                end  = n_samples - i0 - 1
                if end > 0:
                    coherent_sum[:end] += (
                        (1 - frac) * analytic[ie, :end]
                        +      frac  * analytic[ie, 1:end + 1]
                    )

            intensity[iz, ix] = float(np.max(np.abs(coherent_sum)))

    peak_val     = np.max(intensity)
    intensity_db = 20 * np.log10(intensity / (peak_val + 1e-12) + 1e-12)
    peak_idx      = np.unravel_index(np.argmax(intensity), intensity.shape)
    peak_location = (float(x_axis[peak_idx[1]]), float(z_axis[peak_idx[0]]))

    return PAMResult(
        intensity=intensity,
        intensity_db=intensity_db,
        x_axis=x_axis,
        z_axis=z_axis,
        peak_location=peak_location,
    )


# ---------------------------------------------------------------------------
# Signal simulator
# ---------------------------------------------------------------------------

def simulate_array_signals(
    source_position: tuple[float, float],
    array: ArrayGeometry,
    fs: float = 100e6,
    duration: float = 80e-6,
    c: float = 1540.0,
    regime: str = "inertial",
    snr_db: float = 20.0,
    seed: int = 42,
) -> np.ndarray:
    """
    Simulate multi-element passive array signals from a point source.

    Each element receives a time-delayed copy of a synthetic source
    waveform. The waveform envelope peak is aligned to the expected
    TOF delay so that the beamformer can localise correctly.

    Parameters
    ----------
    source_position : (x, z) in metres — z > 0 for subsurface sources.
    array : ArrayGeometry
    fs : float
        Sample rate (Hz).
    duration : float
        Total receive window duration (s). Must exceed max_TOF.
    c : float
        Speed of sound (m/s).
    regime : str
        Cavitation regime — passed to pcd.signals.generate_signal().
    snr_db : float
        Per-element SNR relative to peak waveform amplitude (dB).
    seed : int

    Returns
    -------
    signals : np.ndarray, shape (N_elements, N_samples)
    """
    from .signals import generate_signal, SignalParams

    rng        = np.random.default_rng(seed)
    n_samples  = int(fs * duration)
    n_elements = len(array.element_positions)

    # Source waveform: generate at ~35% of receive window so it fits with delays
    src_params = SignalParams(fs=fs, duration=duration * 0.35, snr_db=50, seed=seed)
    _, source_waveform = generate_signal(regime, src_params)   # type: ignore
    n_src = len(source_waveform)

    # Find envelope peak to align to TOF insertion point
    env_peak_idx = int(np.argmax(np.abs(hilbert(source_waveform))))

    noise_amp = 10 ** (-snr_db / 20)
    src       = np.array(source_position)
    signals   = np.zeros((n_elements, n_samples))

    for ie, ep in enumerate(array.element_positions):
        tof          = np.linalg.norm(src - ep) / c
        tof_samp     = int(round(tof * fs))
        insert_start = tof_samp - env_peak_idx

        src_start = max(0, -insert_start)
        dst_start = max(0,  insert_start)
        copy_len  = min(n_src - src_start, n_samples - dst_start)

        if copy_len > 0:
            signals[ie, dst_start:dst_start + copy_len] = (
                source_waveform[src_start:src_start + copy_len]
            )

        signals[ie] += rng.normal(0, noise_amp, n_samples)

    return signals
