"""
pcd.feedback
------------
PCD feedback layer — live (or synthetic) channel ingest → PCDReading.

Sits between a receive array and a therapy controller. It decides what
happened acoustically and how much to trust that judgment; it never
touches the transducer or chooses the next pulse.

Pipeline
--------
1. Ingest / window a frame (optional ring buffer)
2. Feature extraction (pcd.features)
3. Classification with confidence (pcd.classifier)
4. Localization on a decimated cadence (pcd.beamformer), optional
5. Emit PCDReading (pull via process_frame, or push via subscribe)

Context (free papers)
---------------------
Closed-loop PCD timing precedent and PAM background:
https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4526372/
https://arxiv.org/abs/2412.02413
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Optional

import numpy as np

from .beamformer import ArrayGeometry, gcc_phat_map
from .classifier import ClassifierConfig, classify
from .features import active_burst_window, extract_features

SCHEMA_VERSION = "1.0.0"


class CavitationRegime(Enum):
    NONE = "none"
    STABLE = "stable"
    INERTIAL = "inertial"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ReadingStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"  # produced, but low confidence / partial data
    NO_READING = "no_reading"  # deadline missed or hard fault — do not act


@dataclass
class PCDReading:
    """Structured, low-latency reading for a therapy controller."""

    schema_version: str
    frame_id: int
    timestamp: float
    status: ReadingStatus
    regime: CavitationRegime
    confidence: float  # 0.0–1.0
    location_estimate: Optional[tuple[float, ...]]  # array coords, or None
    location_uncertainty: Optional[float]  # e.g. -3 dB spot size proxy
    dose_proxy: Optional[float]
    latency_ms: float  # measured end-to-end for this frame
    stage_latency_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serialisable form of the 1.0.0 contract (see docs/PCDREADING.md)."""
        loc = self.location_estimate
        return {
            "schema_version": self.schema_version,
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "regime": self.regime.value,
            "confidence": self.confidence,
            "location_estimate": list(loc) if loc is not None else None,
            "location_uncertainty": self.location_uncertainty,
            "dose_proxy": self.dose_proxy,
            "latency_ms": self.latency_ms,
            "stage_latency_ms": dict(self.stage_latency_ms),
        }


@dataclass
class FeedbackConfig:
    """Runtime knobs for the feedback engine."""

    fs: float = 50e6
    f_drive: float = 1.0e6
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    # Confidence below this → DEGRADED (still a reading; controller may ignore)
    confidence_floor: float = 0.35
    # Soft deadline; exceeding it yields NO_READING (fail safe)
    deadline_ms: float | None = 1000.0
    # Localization cadence: 1 = every frame; N = every Nth frame; 0 = never
    localize_every_n: int = 5
    # Beamformer grid (kept coarse for interpulse budgets)
    localize_grid_points: int = 40
    x_range: tuple[float, float] = (-10e-3, 10e-3)
    z_range: tuple[float, float] = (20e-3, 60e-3)
    # Ring buffer depth in frames (0 disables)
    ring_frames: int = 4
    # Channel index used for spectral features when multi-channel
    feature_channel: int = 0
    # Crop RF to the active energy burst before features (fixes array-path
    # CI dilution when the source only fills part of the receive window)
    window_to_burst: bool = True


class PCDFeedbackEngine:
    """
    Feedback layer: channel frame in → PCDReading out.

    Decouples sensing from actuation: never drives the transducer.
    """

    def __init__(
        self,
        config: FeedbackConfig | None = None,
        array: ArrayGeometry | None = None,
    ) -> None:
        self.config = config or FeedbackConfig()
        self.array = array
        self._frame_id = 0
        self._subscribers: list[Callable[[PCDReading], None]] = []
        self._ring: Deque[np.ndarray] = deque(maxlen=max(0, self.config.ring_frames))
        self._last_location: Optional[tuple[float, ...]] = None
        self._last_location_uncertainty: Optional[float] = None
        self.last_stage_latency_ms: dict[str, float] = {}

    def subscribe(self, callback: Callable[[PCDReading], None]) -> None:
        """Push path — controller reacts asynchronously to readings."""
        self._subscribers.append(callback)

    def process_frame(
        self,
        channel_data: np.ndarray,
        trigger_timestamp: float,
    ) -> PCDReading:
        """
        Synchronous pull path — controller calls on its own clock.

        Parameters
        ----------
        channel_data :
            1-D RF window ``(N_samples,)`` or multi-channel
            ``(N_elements, N_samples)``.
        trigger_timestamp :
            Pulse-trigger time (seconds, controller clock).
        """
        t0 = time.perf_counter()
        stages: dict[str, float] = {}
        frame_id = self._frame_id
        self._frame_id += 1

        try:
            data = np.asarray(channel_data, dtype=float)
            if data.ndim == 1:
                data = data[np.newaxis, :]
            if data.ndim != 2:
                raise ValueError(
                    f"channel_data must be 1-D or 2-D, got shape {data.shape}"
                )

            if self.config.ring_frames > 0:
                self._ring.append(data.copy())

            # --- features ---
            t_feat = time.perf_counter()
            ch = int(np.clip(self.config.feature_channel, 0, data.shape[0] - 1))
            signal = data[ch]
            if self.config.window_to_burst:
                i0, i1 = active_burst_window(signal)
                signal = signal[i0:i1]
            n = signal.shape[0]
            if n < 8:
                raise ValueError("feature window too short after burst crop")
            t_axis = np.arange(n, dtype=float) / self.config.fs
            features = extract_features(
                t_axis, signal, f_drive=self.config.f_drive
            )
            stages["features_ms"] = (time.perf_counter() - t_feat) * 1e3

            # --- classify ---
            t_clf = time.perf_counter()
            result = classify(features, config=self.config.classifier)
            stages["classify_ms"] = (time.perf_counter() - t_clf) * 1e3

            regime = _map_regime(result.label)
            confidence = float(result.confidence)
            if regime == CavitationRegime.INERTIAL:
                dose_proxy = float(features.icd)
            elif regime == CavitationRegime.MIXED:
                dose_proxy = float(max(features.icd, features.scd))
            else:
                dose_proxy = float(features.scd)

            # --- localize (decimated) ---
            location = self._last_location
            loc_unc = self._last_location_uncertainty
            ran_localize = False
            every = self.config.localize_every_n
            if (
                every > 0
                and self.array is not None
                and data.shape[0] >= 2
                and (frame_id % every == 0)
            ):
                t_loc = time.perf_counter()
                pam = gcc_phat_map(
                    data,
                    fs=self.config.fs,
                    array=self.array,
                    x_range=self.config.x_range,
                    z_range=self.config.z_range,
                    grid_points=self.config.localize_grid_points,
                )
                location = (float(pam.peak_location[0]), float(pam.peak_location[1]))
                loc_unc = _spot_size_m(pam.intensity_db, pam.x_axis, pam.z_axis)
                self._last_location = location
                self._last_location_uncertainty = loc_unc
                stages["localize_ms"] = (time.perf_counter() - t_loc) * 1e3
                ran_localize = True
            else:
                stages["localize_ms"] = 0.0

            latency_ms = (time.perf_counter() - t0) * 1e3
            stages["total_ms"] = latency_ms
            self.last_stage_latency_ms = stages

            # --- fail-safe deadline ---
            deadline = self.config.deadline_ms
            if deadline is not None and latency_ms > deadline:
                reading = PCDReading(
                    schema_version=SCHEMA_VERSION,
                    frame_id=frame_id,
                    timestamp=trigger_timestamp,
                    status=ReadingStatus.NO_READING,
                    regime=CavitationRegime.UNKNOWN,
                    confidence=0.0,
                    location_estimate=None,
                    location_uncertainty=None,
                    dose_proxy=None,
                    latency_ms=latency_ms,
                    stage_latency_ms=stages,
                )
                self._emit(reading)
                return reading

            status = ReadingStatus.OK
            if confidence < self.config.confidence_floor:
                status = ReadingStatus.DEGRADED
            # Partial data: multi-channel expected location but never ran yet
            if (
                self.array is not None
                and data.shape[0] >= 2
                and location is None
                and not ran_localize
            ):
                status = ReadingStatus.DEGRADED

            reading = PCDReading(
                schema_version=SCHEMA_VERSION,
                frame_id=frame_id,
                timestamp=trigger_timestamp,
                status=status,
                regime=regime,
                confidence=confidence,
                location_estimate=location,
                location_uncertainty=loc_unc,
                dose_proxy=dose_proxy,
                latency_ms=latency_ms,
                stage_latency_ms=stages,
            )
            self._emit(reading)
            return reading

        except Exception:
            latency_ms = (time.perf_counter() - t0) * 1e3
            stages["total_ms"] = latency_ms
            self.last_stage_latency_ms = stages
            reading = PCDReading(
                schema_version=SCHEMA_VERSION,
                frame_id=frame_id,
                timestamp=trigger_timestamp,
                status=ReadingStatus.NO_READING,
                regime=CavitationRegime.UNKNOWN,
                confidence=0.0,
                location_estimate=None,
                location_uncertainty=None,
                dose_proxy=None,
                latency_ms=latency_ms,
                stage_latency_ms=stages,
            )
            self._emit(reading)
            return reading

    def _emit(self, reading: PCDReading) -> None:
        for cb in self._subscribers:
            cb(reading)


def _map_regime(label: str) -> CavitationRegime:
    try:
        return CavitationRegime(label)
    except ValueError:
        return CavitationRegime.UNKNOWN


def _spot_size_m(
    intensity_db: np.ndarray,
    x_axis: np.ndarray,
    z_axis: np.ndarray,
    threshold_db: float = -3.0,
) -> float:
    """Approximate -3 dB spot size as sqrt of above-threshold area."""
    mask = intensity_db >= threshold_db
    if not np.any(mask):
        return float("nan")
    dx = float(np.median(np.diff(x_axis))) if len(x_axis) > 1 else 0.0
    dz = float(np.median(np.diff(z_axis))) if len(z_axis) > 1 else 0.0
    area = float(np.count_nonzero(mask)) * abs(dx) * abs(dz)
    return float(np.sqrt(max(area, 0.0)))
