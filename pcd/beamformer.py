"""
pcd.beamformer
--------------
Passive acoustic source localisation and cavitation mapping.

Algorithms
----------
1. gcc_phat_map  (recommended for broadband point localisation)
   GCC-PHAT TDOA grid search — robust for inertial emissions.

2. delay_and_sum  (classic TEA-style DAS, for comparison)
   Coherent delay-and-sum on analytic signals.

3. delay_multiply_and_sum  (HO-DMAS)
   Higher-order Delay Multiply and Sum with linear complexity via
   Macdonald determinants of power sums. Order j=1 recovers DAS-like
   TEA; j=2 is classic DMAS; j=3–5 is the recommended monitoring
   default; j≥10 can degrade at low SNR.

Coordinate system
-----------------
   - Array face at z = 0.
   - Tissue and imaging grid at z > 0 (positive axial).
   - Lateral axis is x, symmetric about 0.

Context (free papers)
---------------------
Array-based passive cavitation mapping is the clinical motivation for
this module — open overview in Gyöngy's Oxford thesis:
https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d
and recent open PAM beamforming reviews on arXiv, e.g.
https://arxiv.org/abs/2412.02413 and https://arxiv.org/abs/2412.02327.
Angular-spectrum PAM (open full text):
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5565398/
HO-DMAS with linear complexity (open preprint):
https://ssrn.com/abstract=5029537
Same Newton–Girard HO-DMAS idea in open work:
https://arxiv.org/abs/2203.14906
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from scipy.signal import hilbert, resample


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
# Higher-order Delay Multiply and Sum (linear-complexity HO-DMAS)
# ---------------------------------------------------------------------------

def _signed_root(x: np.ndarray, order: int) -> np.ndarray:
    """Signed j-th root compression: sign(x) * |x|**(1/j)."""
    if order == 1:
        return x
    return np.sign(x) * np.abs(x) ** (1.0 / order)


def _elementary_from_power_sums(power_sums: np.ndarray, order: int) -> np.ndarray:
    """
    Elementary symmetric sum E_j(t) from power sums via Newton–Girard.

    ``power_sums`` has shape (j, T) with power_sums[k-1] == e_k(t).
    Returns E_j with shape (T,). Equivalent to Macdonald det / j!
    but vectorised over time.
    """
    # E[k] holds E_k for k = 0..j; E_0 = 1
    n_t = power_sums.shape[1]
    e_sym = [np.ones(n_t, dtype=float)]
    for k in range(1, order + 1):
        acc = np.zeros(n_t, dtype=float)
        for i in range(1, k + 1):
            sign = 1.0 if (i % 2) == 1 else -1.0
            acc += sign * e_sym[k - i] * power_sums[i - 1]
        e_sym.append(acc / float(k))
    return e_sym[order]


def _dmas_prefactor(n_elements: int, order: int) -> float:
    """1 / P(N, j) = 1 / (N * (N-1) * … * (N-j+1))."""
    pref = 1.0
    for m in range(order):
        pref /= float(n_elements - m)
    return pref


def _upsample_for_dmas(
    signals: np.ndarray,
    fs: float,
    order: int,
    f_high: float | None,
) -> tuple[np.ndarray, float]:
    """
    Upsample RF channels to accommodate spectral stretching from products.

    Empirical rule: fs ≈ 5 * f_high * (1 + 0.1*(j-1)).
    When ``f_high`` is None, scale the current rate by (1 + 0.1*(j-1)).
    """
    if order <= 1:
        return signals, fs

    if f_high is not None:
        target_fs = 5.0 * f_high * (1.0 + 0.1 * (order - 1))
    else:
        target_fs = fs * (1.0 + 0.1 * (order - 1))

    if target_fs <= fs * 1.01:
        return signals, fs

    n_new = int(round(signals.shape[1] * target_fs / fs))
    up = np.vstack([resample(ch, n_new) for ch in signals])
    return up, target_fs


def _delayed_channels(
    signals: np.ndarray,
    rel_delays_samples: np.ndarray,
) -> np.ndarray:
    """
    Linearly interpolate each channel by a fractional sample delay.

    Returns array shape (N_elements, N_samples) with zeros in undefined
    leading samples (causal relative delay).
    """
    n_elements, n_samples = signals.shape
    delayed = np.zeros_like(signals, dtype=float)

    for ie in range(n_elements):
        d = float(rel_delays_samples[ie])
        i0 = int(np.floor(d))
        frac = d - i0
        end = n_samples - i0 - 1
        if end <= 0:
            continue
        delayed[ie, :end] = (
            (1.0 - frac) * signals[ie, :end]
            + frac * signals[ie, 1 : end + 1]
        )
    return delayed


def delay_multiply_and_sum(
    signals: np.ndarray,
    fs: float,
    array: ArrayGeometry,
    order: int = 5,
    x_range: tuple[float, float] = (-10e-3, 10e-3),
    z_range: tuple[float, float] = (20e-3, 60e-3),
    grid_points: int = 80,
    c: float = 1540.0,
    upsample: bool = True,
    f_high: float | None = None,
    gate_s: float | None = None,
) -> PAMResult:
    """
    Higher-order Delay Multiply and Sum (DMASj) passive cavitation map.

    Linear-complexity HO-DMAS: signed j-th-root compression, power sums,
    and Macdonald / Newton–Girard elementary symmetric sums so order-j
    products cost O(j² · N · T) per pixel instead of combinatorial O(N^j).
    Open preprint of this formulation: https://ssrn.com/abstract=5029537

    Intensity uses time-exposure acoustics (TEA): sum of q_j(t)^2 over a
    TOF-centred gate at each pixel (full window if ``gate_s`` is None and
    the receive buffer is short).

    Parameters
    ----------
    signals : np.ndarray, shape (N_elements, N_samples)
        Real RF channel data.
    fs : float
        Sample rate (Hz).
    array : ArrayGeometry
    order : int
        DMAS order j. 1 ≈ DAS TEA, 2 = classic DMAS, 3–5 recommended
        for monitoring (order 10 can fail at low SNR).
    x_range, z_range : (float, float)
        Grid extents in metres.
    grid_points : int
        Points per axis.
    c : float
        Speed of sound (m/s).
    upsample : bool
        If True, resample channels to accommodate product-induced
        bandwidth growth.
    f_high : float or None
        Upper transducer bandwidth (Hz) for the sampling rule above.
        If None, scale ``fs`` by (1 + 0.1*(j-1)).
    gate_s : float or None
        Half-width of the TEA integration gate in seconds, centred on
        the minimum element TOF. Default: 15 µs (suited to short
        synthetic pulses). Set to 0 to integrate the full buffer.

    Returns
    -------
    PAMResult
    """
    if order < 1:
        raise ValueError(f"DMAS order must be >= 1, got {order}")

    n_elements, _ = signals.shape
    if n_elements != len(array.element_positions):
        raise ValueError("signals rows must match array element count")
    if n_elements < order:
        raise ValueError(
            f"Need at least {order} elements for DMAS order {order}, "
            f"got {n_elements}"
        )

    work, work_fs = (
        _upsample_for_dmas(signals, fs, order, f_high)
        if upsample
        else (np.asarray(signals, dtype=float), fs)
    )
    work = np.asarray(work, dtype=float)
    pref = _dmas_prefactor(n_elements, order)
    elem_pos = array.element_positions
    if gate_s is None:
        gate_s = 15e-6
    gate_half = int(max(0.0, gate_s) * work_fs)

    x_axis = np.linspace(x_range[0], x_range[1], grid_points)
    z_axis = np.linspace(z_range[0], z_range[1], grid_points)
    intensity = np.zeros((len(z_axis), len(x_axis)))

    for iz, z in enumerate(z_axis):
        for ix, x in enumerate(x_axis):
            r = np.array([x, z])
            tofs = np.linalg.norm(elem_pos - r, axis=1) / c
            rel_delays = (tofs - tofs.min()) * work_fs
            delayed = _delayed_channels(work, rel_delays)

            compressed = _signed_root(delayed, order)  # (N, T)

            power_sums = np.empty((order, delayed.shape[1]), dtype=float)
            power_sums[0] = compressed.sum(axis=0)
            powered = compressed.copy()
            for k in range(1, order):
                powered *= compressed
                power_sums[k] = powered.sum(axis=0)

            e_j = _elementary_from_power_sums(power_sums, order)
            q = pref * e_j

            # TEA over a TOF-centred gate (relative delays align energy near min TOF)
            if gate_half > 0:
                center = int(tofs.min() * work_fs)
                lo = max(0, center - gate_half)
                hi = min(q.shape[0], center + gate_half)
                q_win = q[lo:hi]
            else:
                q_win = q
            intensity[iz, ix] = float(np.dot(q_win, q_win)) if q_win.size else 0.0

    peak_val = np.max(intensity)
    intensity_db = 20 * np.log10(intensity / (peak_val + 1e-12) + 1e-12)
    peak_idx = np.unravel_index(np.argmax(intensity), intensity.shape)
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

    # Source waveform duration fraction of the receive window (TOF headroom).
    # Use the same SNR calibration as direct generate_signal paths (≈20 dB):
    # snr_db=50 here collapses CI because residual drive leakage dominates
    # after peak-normalisation, then channel noise is added separately below.
    SOURCE_DURATION_FRACTION = 0.35
    src_params = SignalParams(
        fs=fs, duration=duration * SOURCE_DURATION_FRACTION, snr_db=20, seed=seed
    )
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
