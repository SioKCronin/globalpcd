"""
Synthetic multi-channel frame stream for feedback-layer tests.

Yields array RF frames from :func:`pcd.beamformer.simulate_array_signals`
so localization can be exercised without hardware.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Literal

import numpy as np

from .beamformer import ArrayGeometry, simulate_array_signals

CavitationRegime = Literal["none", "stable", "inertial"]


def iter_array_frames(
    source_position: tuple[float, float],
    array: ArrayGeometry,
    regimes: Sequence[CavitationRegime] | CavitationRegime = "inertial",
    *,
    fs: float = 50e6,
    duration: float = 80e-6,
    snr_db: float = 25.0,
    n_frames: int | None = None,
    seed: int = 0,
    seed_step: int = 1,
) -> Iterator[tuple[int, np.ndarray]]:
    """
    Yield ``(frame_id, channel_data)`` with shape ``(N_elements, N_samples)``.
    """
    if isinstance(regimes, str):
        cycle: Sequence[CavitationRegime] = (regimes,)
    else:
        cycle = tuple(regimes)
        if not cycle:
            raise ValueError("regimes sequence must be non-empty")

    frame_id = 0
    while n_frames is None or frame_id < n_frames:
        regime = cycle[frame_id % len(cycle)]
        channels = simulate_array_signals(
            source_position=source_position,
            array=array,
            fs=fs,
            duration=duration,
            regime=regime,
            snr_db=snr_db,
            seed=seed + frame_id * seed_step,
        )
        yield frame_id, channels
        frame_id += 1
