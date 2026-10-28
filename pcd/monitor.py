"""
pcd.monitor
-----------
Beside-run monitor for a free-running OpenLIFU sonication.

Open-LIFU fires pulses on its own clock. ``start_sonication`` starts a
free-running trigger, and the run does not pause for a reading before the
next pulse. The hook the app already reserves is an abort callback
(``OpenLIFUSonicationControlLogic.abort``). This module is that shape:

- one single-channel window per pulse
- ``process_frame`` while the trigger keeps its schedule
- a pulse that comes due while a frame is still computing is missed,
  and is not replayed as a live reading
- inertial at high confidence, ``no_reading``, or a missed pulse calls
  ``on_abort``
- nothing here starts the transmitter

Timing is the published Open-LIFU sequence specification (typical row):
400 kHz, 5 ms pulse, 100 ms pulse interval; the minimum interval is 10 ms.
The 155 kHz hardware variant is outside ``SignalParams.lifu`` (200–650 kHz),
so the harness uses 400 kHz.

The receive window is the 200 µs LIFU preset, not the whole 5 ms pulse.
That preset is what the classifier is calibrated on. The budget the
reading has to meet is the pulse interval.

The clock is logical. Busy time is ``PCDReading.latency_ms`` (or an
injected ``busy_s``). The loop does not sleep the interval, so a test can
check the race against 10 ms and 100 ms without waiting out a train.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from .feedback import (
    CavitationRegime,
    PCDFeedbackEngine,
    PCDReading,
    ReadingStatus,
)

logger = logging.getLogger("pcd.monitor")


@dataclass(frozen=True)
class OpenLIFUTiming:
    """Stand-in clock from the published Open-LIFU sequence specification."""

    f_drive_hz: float = 400e3
    pri_s: float = 0.1
    min_pri_s: float = 0.01
    pulse_duration_s: float = 5e-3
    pulses_per_train: int = 300

    def __post_init__(self) -> None:
        if self.pri_s <= 0 or self.min_pri_s <= 0:
            raise ValueError("pulse intervals must be > 0")
        if self.min_pri_s > self.pri_s:
            raise ValueError("min_pri_s cannot exceed pri_s")


@dataclass(frozen=True)
class MonitorEvent:
    """One pulse on the free-running clock."""

    pulse_index: int
    due_s: float
    reading: PCDReading | None
    missed: bool
    abort_requested: bool


def request_stop(reading: PCDReading, *, confidence: float = 0.5) -> bool:
    """Abort request: high-confidence inertial, or no reading at all.

    ``mixed`` is left to the controller. The only actuation hook this
    harness calls is abort, which the discussion reserved for inertial
    and for a reading that never arrived.
    """
    if reading.status == ReadingStatus.NO_READING:
        return True
    return (
        reading.regime == CavitationRegime.INERTIAL
        and reading.confidence >= confidence
    )


def run_beside_trigger(
    engine: PCDFeedbackEngine,
    frames: Sequence[np.ndarray],
    *,
    pri_s: float,
    on_abort: Callable[[], None],
    stop_if: Callable[[PCDReading], bool] | None = None,
    busy_s: Callable[[PCDReading], float] | None = None,
) -> list[MonitorEvent]:
    """
    Run ``engine`` beside a trigger that does not wait.

    Pulse ``k`` is due at ``k * pri_s``. The monitor accepts it only when
    idle. Compute time is ``reading.latency_ms`` unless ``busy_s`` is
    set. The next pulse that falls inside that window is a miss: no
    reading is emitted for it, and ``on_abort`` is called.

    ``on_abort`` is the session's abort. This function does not receive
    a transmitter and cannot start one.
    """
    if pri_s <= 0:
        raise ValueError(f"pri_s must be > 0, got {pri_s}")
    decide = stop_if if stop_if is not None else request_stop
    events: list[MonitorEvent] = []
    free_at = 0.0
    stopped = False

    for k, frame in enumerate(frames):
        if stopped:
            break
        due = k * pri_s
        if due < free_at:
            event = MonitorEvent(
                pulse_index=k,
                due_s=due,
                reading=None,
                missed=True,
                abort_requested=True,
            )
            events.append(event)
            _log_event(event)
            on_abort()
            stopped = True
            break

        reading = engine.process_frame(np.asarray(frame), due)
        compute_s = reading.latency_ms / 1e3 if busy_s is None else float(busy_s(reading))
        if compute_s < 0:
            raise ValueError(f"busy time must be >= 0, got {compute_s}")
        free_at = due + compute_s
        stop = bool(decide(reading))
        event = MonitorEvent(
            pulse_index=k,
            due_s=due,
            reading=reading,
            missed=False,
            abort_requested=stop,
        )
        events.append(event)
        _log_event(event)
        if stop:
            on_abort()
            stopped = True

    return events


def _log_event(event: MonitorEvent) -> None:
    """Schedule decision for one pulse. The reading itself is logged by the engine."""
    regime = "null" if event.reading is None else event.reading.regime.value
    level = logging.WARNING if event.missed or event.abort_requested else logging.INFO
    logger.log(
        level,
        "pulse=%d due_s=%.6f missed=%s abort=%s regime=%s",
        event.pulse_index,
        event.due_s,
        str(event.missed).lower(),
        str(event.abort_requested).lower(),
        regime,
    )
