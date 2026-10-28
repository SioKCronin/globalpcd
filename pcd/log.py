"""
pcd.log
-------
One-line developer log for a frame the engine returns.

The library does not configure logging. A host turns the lines on with
``logging.getLogger("pcd")``. Successful readings are INFO. A deadline
miss is WARNING. A fault is ERROR and still returns ``no_reading``.

The line is the reading, not the RF. Schema fields are unchanged.
See docs/LOGGING.md.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger("pcd.reading")


def format_features(features) -> str:
    """Compact spectral summary. No spectrum arrays."""
    snr = float(features.subharmonic_snr)
    snr_s = "inf" if math.isinf(snr) else f"{snr:.1f}"
    return (
        f"sub_amp={float(features.subharmonic_amp):.4f} "
        f"snr={snr_s} "
        f"ci={float(features.cavitation_index):.3f}"
    )


def format_reading(reading, *, reason: str, detail: str | None = None) -> str:
    """Single greppable line. ``reason`` is ``reading``, ``deadline``, or ``fault``."""
    loc = reading.location_estimate
    if loc is None:
        loc_s = "null"
    else:
        loc_s = ",".join(f"{float(v):.6g}" for v in loc)
    parts = [
        f"frame={reading.frame_id}",
        f"t={float(reading.timestamp):.6f}",
        f"status={reading.status.value}",
        f"regime={reading.regime.value}",
        f"confidence={float(reading.confidence):.3f}",
        f"latency_ms={float(reading.latency_ms):.2f}",
        f"reason={reason}",
        f"loc={loc_s}",
    ]
    stages = reading.stage_latency_ms or {}
    for key in ("features_ms", "classify_ms", "localize_ms"):
        if key in stages:
            parts.append(f"{key}={float(stages[key]):.2f}")
    if detail:
        parts.append(" ".join(str(detail).split()))
    return " ".join(parts)


def log_reading(
    reading,
    *,
    reason: str,
    detail: str | None = None,
    exc_info: bool = False,
) -> None:
    """Write one line. Handler errors stay inside the logging module."""
    line = format_reading(reading, reason=reason, detail=detail)
    if reason == "fault":
        logger.error(line, exc_info=exc_info)
    elif reading.status.value == "no_reading":
        logger.warning(line)
    else:
        logger.info(line)
