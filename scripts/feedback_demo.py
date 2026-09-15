#!/usr/bin/env python3
"""
Smoke demo for pull + push feedback paths.

For the richer mocked controller (ramp / hold / reduce-pressure), see
``examples/mock_controller.py``.
"""

from __future__ import annotations

from pcd import (
    ArrayGeometry,
    FeedbackConfig,
    PCDFeedbackEngine,
    ReadingStatus,
    SignalParams,
    iter_array_frames,
    iter_signals,
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
    for frame_id, _t, signal in iter_signals(
        ["none", "stable", "inertial"],
        SignalParams(fs=20e6, duration=40e-6, snr_db=25),
        n_frames=6,
    ):
        reading = engine.process_frame(signal, trigger_timestamp=frame_id * 0.01)
        print(
            f"  frame={reading.frame_id}: {reading.status.value} "
            f"{reading.regime.value} conf={reading.confidence:.2f} "
            f"latency={reading.latency_ms:.2f} ms"
        )


def demo_push_array() -> None:
    print("\n=== Push path (subscribe) — multi-channel + burst-windowed features ===")
    array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=25e6,
            f_drive=1e6,
            localize_every_n=2,
            localize_grid_points=30,
            deadline_ms=5_000.0,
            window_to_burst=True,
            x_range=(-8e-3, 8e-3),
            z_range=(25e-3, 50e-3),
        ),
        array=array,
    )
    seen = []
    engine.subscribe(seen.append)

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
        engine.process_frame(channels, trigger_timestamp=frame_id * 0.01)

    for reading in seen:
        loc = reading.location_estimate
        loc_s = (
            f"({loc[0]*1e3:.1f}, {loc[1]*1e3:.1f}) mm" if loc is not None else "n/a"
        )
        flag = ""
        if reading.status == ReadingStatus.DEGRADED:
            flag = " [degraded]"
        elif reading.status == ReadingStatus.NO_READING:
            flag = " [no_reading]"
        print(
            f"  frame={reading.frame_id}: {reading.regime.value} "
            f"conf={reading.confidence:.2f} loc={loc_s}{flag}"
        )


if __name__ == "__main__":
    demo_pull_single_channel()
    demo_push_array()
