"""Tests for TX-trigger session + receive sources (no hardware)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pcd import ArrayGeometry, FeedbackConfig, PCDFeedbackEngine
from pcd.hw import (
    FeedbackSession,
    FileReplaySource,
    OpenLIFUTriggerClock,
    ReceiveFrame,
    SoftwarePRFClock,
    SyntheticReceiveSource,
    try_openlifu_tx,
)


class FakeTx:
    def __init__(self, start_ok: bool = True) -> None:
        self.started = False
        self.stopped = False
        self.trigger_json = None
        self.start_ok = start_ok

    def set_trigger_json(self, data=None, **_kwargs):
        self.trigger_json = data
        return data

    def start_trigger(self):
        self.started = True
        return self.start_ok

    def stop_trigger(self):
        self.stopped = True
        return True


class TestReceiveSources:
    def test_synthetic_yields_then_none(self):
        array = ArrayGeometry.linear(n_elements=4, pitch=1.5e-3)
        src = SyntheticReceiveSource.from_array(
            (0.0, 35e-3),
            array,
            regimes="inertial",
            fs=20e6,
            duration=40e-6,
            n_frames=2,
        )
        f0 = src.next_frame()
        f1 = src.next_frame()
        assert f0 is not None and f1 is not None
        assert f0.channel_data.ndim == 2
        assert src.next_frame() is None

    def test_file_replay_roundtrip(self, tmp_path: Path):
        frames = np.random.default_rng(0).normal(size=(3, 4, 32))
        path = tmp_path / "rf.npy"
        np.save(path, frames)
        src = FileReplaySource(path)
        got = []
        while True:
            f = src.next_frame()
            if f is None:
                break
            got.append(f.channel_data)
        assert len(got) == 3
        np.testing.assert_array_equal(got[0], frames[0])
        assert got[0].shape == (4, 32)
        assert src.next_frame() is None

    def test_file_replay_2d_requires_layout(self, tmp_path: Path):
        path = tmp_path / "rf.npy"
        np.save(path, np.zeros((10, 1000)))
        with pytest.raises(ValueError, match="layout"):
            FileReplaySource(path)

    def test_file_replay_frames_layout(self, tmp_path: Path):
        frames = np.arange(20, dtype=float).reshape(4, 5)
        path = tmp_path / "rf.npy"
        np.save(path, frames)
        src = FileReplaySource(path, layout="frames")
        first = src.next_frame()
        assert first is not None
        assert first.channel_data.shape == (1, 5)
        assert first.trigger_timestamp is None
        np.testing.assert_array_equal(first.channel_data[0], frames[0])
        rest = []
        while (frame := src.next_frame()) is not None:
            rest.append(frame.channel_data)
        assert len(rest) == 3

    def test_file_replay_channels_layout(self, tmp_path: Path):
        frame = np.arange(12, dtype=float).reshape(3, 4)
        path = tmp_path / "rf.npy"
        np.save(path, frame)
        src = FileReplaySource(path, layout="channels")
        got = src.next_frame()
        assert got is not None
        np.testing.assert_array_equal(got.channel_data, frame)
        assert src.next_frame() is None

    def test_file_replay_layout_rejected_on_3d(self, tmp_path: Path):
        path = tmp_path / "rf.npy"
        np.save(path, np.zeros((2, 3, 4)))
        with pytest.raises(ValueError, match="2-D"):
            FileReplaySource(path, layout="frames")


class TestClocks:
    def test_software_prf_no_pace(self):
        clock = SoftwarePRFClock(prf_hz=100.0, pace=False)
        with clock:
            t0 = clock.wait()
            t1 = clock.wait()
        assert t1 >= t0

    def test_openlifu_clock_is_observe_only_by_default(self):
        tx = FakeTx()
        clock = OpenLIFUTriggerClock(tx=tx, prf_hz=50.0, pace=False)
        with clock:
            assert clock.wait() > 0
        assert not tx.started
        assert not tx.stopped
        assert tx.trigger_json is None

    def test_trigger_json_requires_opt_in(self):
        with pytest.raises(ValueError, match="allow_tx_start"):
            OpenLIFUTriggerClock(
                tx=FakeTx(),
                prf_hz=50.0,
                trigger_json={"TriggerFrequencyHz": 50.0},
            )

    def test_openlifu_clock_starts_and_stops_with_opt_in(self):
        tx = FakeTx()
        clock = OpenLIFUTriggerClock(
            tx=tx,
            prf_hz=50.0,
            trigger_json={"TriggerFrequencyHz": 50.0},
            allow_tx_start=True,
            pace=False,
        )
        with clock:
            ts = clock.wait()
            assert ts > 0
        assert tx.started and tx.stopped
        assert tx.trigger_json["TriggerFrequencyHz"] == 50.0

    def test_openlifu_clock_without_tx(self):
        clock = OpenLIFUTriggerClock(tx=None, prf_hz=20.0, pace=False)
        with clock:
            assert clock.wait() > 0

    def test_start_trigger_failure_raises(self):
        tx = FakeTx(start_ok=False)
        clock = OpenLIFUTriggerClock(
            tx=tx, prf_hz=10.0, allow_tx_start=True, pace=False
        )
        with pytest.raises(RuntimeError, match="start_trigger"):
            with clock:
                pass
        assert tx.stopped  # still stop on exit

    def test_try_openlifu_tx_without_sdk(self):
        tx = try_openlifu_tx()
        assert tx is None or hasattr(tx, "start_trigger")


class TestFeedbackSession:
    def test_session_runs_on_synthetic_rf(self):
        array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=25e6,
                localize_every_n=0,
                deadline_ms=30_000,
            ),
            array=array,
        )
        receive = SyntheticReceiveSource.from_array(
            (1e-3, 35e-3),
            array,
            regimes=["stable", "inertial"],
            fs=25e6,
            duration=50e-6,
            snr_db=35,
            n_frames=4,
        )
        tx = FakeTx()
        session = FeedbackSession(
            engine,
            receive,
            OpenLIFUTriggerClock(tx=tx, prf_hz=100.0, pace=False),
        )
        readings = session.run(n_frames=4)
        assert len(readings) == 4
        assert not tx.started  # sensing session never arms TX by default
        assert [r.frame_id for r in readings] == list(range(4))

    def test_session_stops_when_source_exhausted(self):
        class OneShot:
            def __init__(self) -> None:
                self.done = False

            def next_frame(self):
                if self.done:
                    return None
                self.done = True
                return ReceiveFrame(channel_data=np.zeros(64))

        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=5_000)
        )
        session = FeedbackSession(
            engine, OneShot(), SoftwarePRFClock(prf_hz=100.0, pace=False)
        )
        readings = session.run(n_frames=10)
        assert len(readings) == 1

    def test_session_prefers_frame_trigger_timestamp(self):
        class Stamped:
            def next_frame(self):
                return ReceiveFrame(
                    channel_data=np.zeros(64), trigger_timestamp=123.0
                )

        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=5_000)
        )
        session = FeedbackSession(
            engine, Stamped(), SoftwarePRFClock(prf_hz=100.0, pace=False)
        )
        readings = session.run(n_frames=1)
        assert readings[0].timestamp == 123.0

    def test_session_uses_software_clock_when_frame_has_no_timestamp(self):
        class Untimed:
            def __init__(self) -> None:
                self.done = False

            def next_frame(self):
                if self.done:
                    return None
                self.done = True
                return ReceiveFrame(channel_data=np.zeros(64))

        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=5_000)
        )
        session = FeedbackSession(
            engine, Untimed(), SoftwarePRFClock(prf_hz=100.0, pace=False)
        )
        readings = session.run(n_frames=1)
        assert readings[0].timestamp > 0.0
        assert readings[0].timestamp != 123.0
