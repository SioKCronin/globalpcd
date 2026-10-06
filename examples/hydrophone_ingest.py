#!/usr/bin/env python3
"""
Phase-1 ingest: single hydrophone file → PCDReading.

OpenLIFU has no receive array in the public SDK. The first hardware-shaped
path is one PCD element (WAV or 1-D NumPy) into the feedback engine, with
localization off. This demo uses the LIFU-band synthetic preset
(200–650 kHz) written to WAV, then reloaded as if from a DAQ.

Run from the repo root::

    .venv/bin/python examples/hydrophone_ingest.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pcd import FeedbackConfig, PCDFeedbackEngine, SignalParams, generate_signal
from pcd.hw import HydrophoneFileSource, write_hydrophone_wav

OUT = Path("demo_output") / "hydrophone"


def main() -> None:
    params = SignalParams.lifu(f_drive=500e3)
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=params.fs,
            f_drive=params.f_drive,
            localize_every_n=0,
            deadline_ms=1_000.0,
        )
    )
    OUT.mkdir(parents=True, exist_ok=True)

    print(
        f"LIFU preset: f_drive={params.f_drive/1e3:.0f} kHz  "
        f"fs={params.fs/1e6:.1f} MHz  window={params.duration*1e6:.0f} µs"
    )
    print("ingest: single-element WAV → process_frame (no localization)\n")

    for i, regime in enumerate(("none", "stable", "inertial")):
        _t, signal = generate_signal(regime, SignalParams.lifu(seed=i))
        wav_path = OUT / f"{regime}.wav"
        write_hydrophone_wav(wav_path, signal, params.fs)

        src = HydrophoneFileSource(wav_path)
        frame = src.next_frame()
        assert frame is not None
        reading = engine.process_frame(frame.channel_data, trigger_timestamp=i / 10.0)
        payload = reading.to_dict()
        print(
            f"  expected={regime:10s}  got status={payload['status']:10s} "
            f"regime={payload['regime']:10s} conf={payload['confidence']:.2f} "
            f"latency={payload['latency_ms']:.2f} ms  "
            f"fs={src.fs/1e6:.1f} MHz  samples={frame.channel_data.size}"
        )

    print("\nexample PCDReading JSON:")
    print(json.dumps(payload, indent=2))
    print(f"\nWAV files: {OUT.resolve()}")


if __name__ == "__main__":
    main()
