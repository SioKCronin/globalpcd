#!/usr/bin/env python3
"""
OpenLIFU TX-trigger session with synthetic (or file) RF.

Until a passive receive DAQ exists, this loop:

1. Observes an OpenLIFU TX module if connected; starts/stops its trigger
   ONLY with ``--start-tx`` (bench use — globalPCD is sensing-only by default)
2. Paces frames at the configured PRF in software
3. Pulls RF from a ReceiveSource (synthetic array or ``.npy`` replay)
4. Emits PCDReading — never chooses the next pulse

Run from the repo root::

    .venv/bin/python examples/openlifu_trigger_session.py
    .venv/bin/python examples/openlifu_trigger_session.py --npy path/to/rf.npy
    .venv/bin/python examples/openlifu_trigger_session.py --start-tx   # bench only
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pcd import (
    ArrayGeometry,
    FeedbackConfig,
    PCDFeedbackEngine,
    ReadingStatus,
)
from pcd.hw import (
    FeedbackSession,
    FileReplaySource,
    OpenLIFUTriggerClock,
    SyntheticReceiveSource,
    try_openlifu_tx,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--npy",
        type=Path,
        default=None,
        help="Replay RF from a .npy file instead of synthetic frames",
    )
    parser.add_argument("--prf", type=float, default=10.0, help="Trigger PRF (Hz)")
    parser.add_argument("--n-frames", type=int, default=6)
    parser.add_argument(
        "--pace",
        action="store_true",
        help="Sleep to match PRF (default: run as fast as compute allows)",
    )
    parser.add_argument(
        "--start-tx",
        action="store_true",
        help="Arm and stop the OpenLIFU TX trigger (bench only; off by default)",
    )
    args = parser.parse_args()

    tx = try_openlifu_tx()
    if tx is None:
        print("OpenLIFU TX: not connected (software PRF clock)")
    else:
        if args.start_tx:
            print("OpenLIFU TX: connected — --start-tx given, arming trigger for session")
        else:
            print("OpenLIFU TX: connected — observe-only (pass --start-tx to arm)")

    array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=25e6,
            f_drive=1e6,
            localize_every_n=2 if args.npy is None else 0,
            localize_grid_points=25,
            deadline_ms=5_000.0,
            x_range=(-8e-3, 8e-3),
            z_range=(25e-3, 50e-3),
        ),
        array=array if args.npy is None else None,
    )

    if args.npy is None:
        receive = SyntheticReceiveSource.from_array(
            (1e-3, 35e-3),
            array,
            regimes=["none", "stable", "inertial"],
            fs=25e6,
            duration=60e-6,
            snr_db=35,
            n_frames=args.n_frames,
        )
        print("RF source: synthetic array frames")
    else:
        receive = FileReplaySource(args.npy)
        print(f"RF source: file replay {args.npy}")

    trigger_json = {
        "TriggerFrequencyHz": args.prf,
        "TriggerPulseCount": 1,
        "TriggerPulseWidthUsec": 10.0,
        "TriggerMode": 2,  # continuous in openlifu-sdk examples
        "ProfileIndex": 0,
        "ProfileIncrement": 0,
    }
    clock = OpenLIFUTriggerClock(
        tx=tx,
        prf_hz=args.prf,
        trigger_json=trigger_json if (tx is not None and args.start_tx) else None,
        allow_tx_start=args.start_tx,
        pace=args.pace,
    )
    readings = FeedbackSession(engine, receive, clock).run(n_frames=args.n_frames)

    for r in readings:
        loc = r.location_estimate
        loc_s = (
            f"({loc[0]*1e3:.1f}, {loc[1]*1e3:.1f}) mm" if loc is not None else "n/a"
        )
        flag = ""
        if r.status == ReadingStatus.DEGRADED:
            flag = " [degraded]"
        elif r.status == ReadingStatus.NO_READING:
            flag = " [no_reading]"
        print(
            f"  frame={r.frame_id}: {r.regime.value:10s} "
            f"conf={r.confidence:.2f} loc={loc_s} "
            f"latency={r.latency_ms:.2f} ms{flag}"
        )


if __name__ == "__main__":
    main()
