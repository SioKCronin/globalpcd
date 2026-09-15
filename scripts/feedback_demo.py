#!/usr/bin/env python3
"""
Mocked therapy-controller integration for the PCD feedback layer.

Shows both interface paths against synthetic data (no hardware):

* ``process_frame`` — controller pulls on its own clock
* ``subscribe`` — controller reacts asynchronously to readings

Run from the repo root::

    .venv/bin/python scripts/feedback_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcd import (
    ArrayGeometry,
    FeedbackConfig,
    PCDFeedbackEngine,
    PCDReading,
    ReadingStatus,
    SignalParams,
    iter_array_frames,
    iter_signals,
)


@dataclass
class MockController:
    """Stand-in for a therapy controller (e.g. OpenLIFU)."""

    name: str = "MockOpenLIFU"
    readings: list[PCDReading] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def on_reading(self, reading: PCDReading) -> None:
        """Push-path handler: decide whether to act, never how to beamform."""
        self.readings.append(reading)
        if reading.status == ReadingStatus.NO_READING:
            self.actions.append(
                f"frame={reading.frame_id}: HOLD (no_reading, "
                f"latency={reading.latency_ms:.2f} ms)"
            )
            return
        if reading.status == ReadingStatus.DEGRADED:
            self.actions.append(
                f"frame={reading.frame_id}: CAUTION regime={reading.regime.value} "
                f"conf={reading.confidence:.2f}"
            )
            return
        loc = reading.location_estimate
        loc_s = (
            f"({loc[0]*1e3:.1f}, {loc[1]*1e3:.1f}) mm" if loc is not None else "n/a"
        )
        self.actions.append(
            f"frame={reading.frame_id}: ACT regime={reading.regime.value} "
            f"conf={reading.confidence:.2f} loc={loc_s} "
            f"dose={reading.dose_proxy:.4g} "
            f"latency={reading.latency_ms:.2f} ms"
        )


def demo_pull_single_channel() -> None:
    print("=== Pull path (process_frame) — single-channel synthetic stream ===")
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=20e6,
            f_drive=1e6,
            localize_every_n=0,
            deadline_ms=1_000.0,
        )
    )
    controller = MockController()
    for frame_id, _t, signal in iter_signals(
        ["none", "stable", "inertial"],
        SignalParams(fs=20e6, duration=40e-6, snr_db=25),
        n_frames=6,
    ):
        reading = engine.process_frame(signal, trigger_timestamp=frame_id * 0.01)
        controller.on_reading(reading)
    for line in controller.actions:
        print(" ", line)


def demo_push_array() -> None:
    print("\n=== Push path (subscribe) — multi-channel + decimated localization ===")
    array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=25e6,
            f_drive=1e6,
            localize_every_n=2,
            localize_grid_points=30,
            deadline_ms=5_000.0,
            x_range=(-8e-3, 8e-3),
            z_range=(25e-3, 50e-3),
        ),
        array=array,
    )
    controller = MockController()
    engine.subscribe(controller.on_reading)

    source = (1e-3, 35e-3)
    for frame_id, channels in iter_array_frames(
        source,
        array,
        regimes=["stable", "inertial"],
        fs=25e6,
        duration=60e-6,
        snr_db=28,
        n_frames=6,
    ):
        # Controller clock pulls frames; callbacks fire inside process_frame
        engine.process_frame(channels, trigger_timestamp=frame_id * 0.01)

    for line in controller.actions:
        print(" ", line)
    print(
        f"  schema={controller.readings[0].schema_version!r}  "
        f"stages={controller.readings[0].stage_latency_ms}"
    )


if __name__ == "__main__":
    demo_pull_single_channel()
    demo_push_array()
