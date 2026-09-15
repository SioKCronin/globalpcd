#!/usr/bin/env python3
"""
Mocked therapy controller standing in for OpenLIFU (or similar).

Demonstrates the integration contract: GlobalPCD's feedback layer emits
``PCDReading`` values; this controller decides ramp / hold / reduce-pressure
from those readings alone. It never touches beamforming or RF.

Run from the repo root::

    .venv/bin/python examples/mock_controller.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pcd import (
    ArrayGeometry,
    CavitationRegime,
    FeedbackConfig,
    PCDFeedbackEngine,
    PCDReading,
    ReadingStatus,
    iter_array_frames,
)


class ControlAction(Enum):
    RAMP = "ramp"  # increase toward target (no cavitation yet)
    HOLD = "hold"  # maintain — reading OK or temporarily blind
    REDUCE_PRESSURE = "reduce_pressure"  # inertial / safety
    CAUTION = "caution"  # degraded confidence — do not escalate


@dataclass
class MockController:
    """
    Stand-in for a therapy controller.

    Policy is intentionally simple and local to this example — real
    platforms own their own control law. GlobalPCD only supplies readings.
    """

    name: str = "MockOpenLIFU"
    readings: list[PCDReading] = field(default_factory=list)
    decisions: list[tuple[int, ControlAction, str]] = field(default_factory=list)
    pressure_fraction: float = 0.5  # 0–1 stand-in for output level

    def on_reading(self, reading: PCDReading) -> ControlAction:
        """Map one PCDReading → control action (sensing/actuation decoupled)."""
        self.readings.append(reading)
        action, note = self._decide(reading)
        self.decisions.append((reading.frame_id, action, note))
        self._apply(action)
        return action

    def _decide(self, reading: PCDReading) -> tuple[ControlAction, str]:
        if reading.status == ReadingStatus.NO_READING:
            return (
                ControlAction.HOLD,
                f"no_reading (latency={reading.latency_ms:.2f} ms) — stay blind-safe",
            )
        if reading.status == ReadingStatus.DEGRADED:
            return (
                ControlAction.CAUTION,
                f"degraded conf={reading.confidence:.2f} regime={reading.regime.value}",
            )

        regime = reading.regime
        conf = reading.confidence
        loc = reading.location_estimate
        loc_s = (
            f"({loc[0] * 1e3:.1f}, {loc[1] * 1e3:.1f}) mm"
            if loc is not None
            else "n/a"
        )

        if regime in (CavitationRegime.INERTIAL, CavitationRegime.MIXED) and conf >= 0.5:
            return (
                ControlAction.REDUCE_PRESSURE,
                f"{regime.value} conf={conf:.2f} loc={loc_s} — safety reduce",
            )
        if regime == CavitationRegime.STABLE and conf >= 0.5:
            return (
                ControlAction.HOLD,
                f"stable conf={conf:.2f} loc={loc_s} — maintain band",
            )
        if regime == CavitationRegime.NONE:
            return (
                ControlAction.RAMP,
                f"none conf={conf:.2f} — ramp toward target",
            )
        return (
            ControlAction.HOLD,
            f"{regime.value} conf={conf:.2f} loc={loc_s}",
        )

    def _apply(self, action: ControlAction) -> None:
        if action == ControlAction.RAMP:
            self.pressure_fraction = min(1.0, self.pressure_fraction + 0.1)
        elif action == ControlAction.REDUCE_PRESSURE:
            self.pressure_fraction = max(0.0, self.pressure_fraction - 0.2)
        # HOLD / CAUTION: leave pressure unchanged


def run_demo() -> MockController:
    array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
    source = (1e-3, 35e-3)
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
    controller = MockController()
    engine.subscribe(controller.on_reading)

    print(f"=== {controller.name}: subscribe path + array synthetic stream ===")
    print(f"True source: ({source[0]*1e3:.1f}, {source[1]*1e3:.1f}) mm")

    for frame_id, channels in iter_array_frames(
        source,
        array,
        regimes=["none", "stable", "inertial"],
        fs=25e6,
        duration=60e-6,
        snr_db=35,
        n_frames=9,
    ):
        engine.process_frame(channels, trigger_timestamp=frame_id * 0.01)

    for frame_id, action, note in controller.decisions:
        print(f"  frame={frame_id}: {action.value:16s}  {note}")

    locs = [r.location_estimate for r in controller.readings if r.location_estimate]
    if locs:
        x, z = locs[-1]
        err_mm = ((x - source[0]) ** 2 + (z - source[1]) ** 2) ** 0.5 * 1e3
        print(
            f"  last location=({x*1e3:.1f}, {z*1e3:.1f}) mm  "
            f"error≈{err_mm:.1f} mm  "
            f"pressure_fraction={controller.pressure_fraction:.2f}"
        )
        print(f"  schema={controller.readings[0].schema_version!r}")
    return controller


if __name__ == "__main__":
    run_demo()
