"""Tests for the PCD feedback layer."""

from __future__ import annotations

import time

import numpy as np
import pytest

from pcd import (
    ArrayGeometry,
    FeedbackConfig,
    PCDFeedbackEngine,
    ReadingStatus,
    SCHEMA_VERSION,
    SignalParams,
    iter_array_frames,
    iter_signals,
)


class TestIterSignals:
    def test_finite_stream_cycles_regimes(self):
        frames = list(
            iter_signals(
                ["none", "stable", "inertial"],
                SignalParams(fs=20e6, duration=20e-6),
                n_frames=5,
            )
        )
        assert len(frames) == 5
        assert [f[0] for f in frames] == list(range(5))
        assert all(s.ndim == 1 and t.ndim == 1 for _, t, s in frames)

    def test_empty_regimes_raises(self):
        with pytest.raises(ValueError):
            next(iter_signals([], n_frames=1))


class TestFeedbackEngine:
    def test_process_frame_schema_and_ok(self):
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, f_drive=1e6, localize_every_n=0, deadline_ms=5_000)
        )
        _, t, signal = next(
            iter_signals("stable", SignalParams(fs=20e6, duration=40e-6), n_frames=1)
        )
        reading = engine.process_frame(signal, trigger_timestamp=0.0)
        assert reading.schema_version == SCHEMA_VERSION
        assert reading.frame_id == 0
        assert reading.status in (ReadingStatus.OK, ReadingStatus.DEGRADED)
        assert 0.0 <= reading.confidence <= 1.0
        assert reading.latency_ms >= 0.0
        assert "features_ms" in reading.stage_latency_ms
        assert "classify_ms" in reading.stage_latency_ms
        assert reading.regime.value in {"none", "stable", "inertial", "mixed", "unknown"}
        assert t is not None

    def test_subscribe_push_path(self):
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=5_000)
        )
        seen = []
        engine.subscribe(seen.append)
        _, _, signal = next(
            iter_signals("inertial", SignalParams(fs=20e6, duration=40e-6), n_frames=1)
        )
        reading = engine.process_frame(signal, trigger_timestamp=1.0)
        assert seen == [reading]

    def test_deadline_miss_is_no_reading(self):
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=0.0)
        )
        _, _, signal = next(
            iter_signals("none", SignalParams(fs=20e6, duration=20e-6), n_frames=1)
        )
        reading = engine.process_frame(signal, trigger_timestamp=0.0)
        assert reading.status == ReadingStatus.NO_READING
        assert reading.regime.value == "unknown"
        assert reading.confidence == 0.0

    def test_hard_fault_is_no_reading(self):
        engine = PCDFeedbackEngine(FeedbackConfig(localize_every_n=0))
        reading = engine.process_frame(np.zeros((2, 2, 2)), trigger_timestamp=0.0)
        assert reading.status == ReadingStatus.NO_READING

    def test_end_to_end_synthetic_stream(self):
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, f_drive=1e6, localize_every_n=0, deadline_ms=5_000)
        )
        labels = []
        for frame_id, _t, signal in iter_signals(
            ["none", "stable", "inertial"],
            SignalParams(fs=20e6, duration=40e-6, snr_db=25),
            n_frames=6,
        ):
            r = engine.process_frame(signal, trigger_timestamp=frame_id * 0.01)
            assert r.status != ReadingStatus.NO_READING
            labels.append(r.regime.value)
        # At least one non-none label on the cycling stream
        assert any(lab != "none" for lab in labels)

    def test_array_stream_localizes_on_cadence(self):
        array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=25e6,
                f_drive=1e6,
                localize_every_n=2,
                localize_grid_points=25,
                deadline_ms=30_000,
                x_range=(-8e-3, 8e-3),
                z_range=(25e-3, 50e-3),
            ),
            array=array,
        )
        source = (0.0, 35e-3)
        locations = []
        for frame_id, channels in iter_array_frames(
            source,
            array,
            regimes="inertial",
            fs=25e6,
            duration=60e-6,
            snr_db=30,
            n_frames=4,
        ):
            r = engine.process_frame(channels, trigger_timestamp=frame_id * 0.01)
            assert r.status in (ReadingStatus.OK, ReadingStatus.DEGRADED)
            locations.append(r.location_estimate)

        # Frame 0 and 2 run localization; odd frames reuse last estimate
        assert locations[0] is not None
        assert locations[1] == locations[0]
        assert locations[2] is not None
        # Peak should be within a few mm of the true source (coarse grid)
        x, z = locations[0]
        assert abs(x - source[0]) < 5e-3
        assert abs(z - source[1]) < 8e-3

    def test_stage_latency_instrumentation(self):
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=20e6, localize_every_n=0, deadline_ms=5_000)
        )
        _, _, signal = next(
            iter_signals("stable", SignalParams(fs=20e6, duration=30e-6), n_frames=1)
        )
        t0 = time.perf_counter()
        reading = engine.process_frame(signal, trigger_timestamp=0.0)
        wall_ms = (time.perf_counter() - t0) * 1e3
        assert reading.latency_ms <= wall_ms + 5.0
        assert engine.last_stage_latency_ms["total_ms"] == reading.latency_ms

    def test_inertial_detected_through_array_path(self):
        """Burst-windowed features should not dilute CI on array-simulated RF."""
        array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=25e6,
                f_drive=1e6,
                localize_every_n=0,
                deadline_ms=30_000,
                window_to_burst=True,
            ),
            array=array,
        )
        _, channels = next(
            iter_array_frames(
                (0.0, 35e-3),
                array,
                regimes="inertial",
                fs=25e6,
                duration=60e-6,
                snr_db=30,
                n_frames=1,
            )
        )
        reading = engine.process_frame(channels, trigger_timestamp=0.0)
        assert reading.status != ReadingStatus.NO_READING
        assert reading.regime.value in {"inertial", "mixed"}

    def test_array_path_without_burst_window_under_detects(self):
        """Documents the dilution bug: full-buffer features miss inertial."""
        array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=25e6,
                f_drive=1e6,
                localize_every_n=0,
                deadline_ms=30_000,
                window_to_burst=False,
            ),
            array=array,
        )
        _, channels = next(
            iter_array_frames(
                (0.0, 35e-3),
                array,
                regimes="inertial",
                fs=25e6,
                duration=60e-6,
                snr_db=30,
                n_frames=1,
            )
        )
        reading = engine.process_frame(channels, trigger_timestamp=0.0)
        # Without windowing, inertial is typically collapsed to none
        assert reading.regime.value in {"none", "stable"}


class TestActiveBurstWindow:
    def test_full_buffer_when_energy_everywhere(self):
        from pcd import active_burst_window, generate_signal, SignalParams

        _, signal = generate_signal(
            "inertial", SignalParams(fs=20e6, duration=40e-6)
        )
        start, end = active_burst_window(signal)
        assert start == 0
        assert end == len(signal)

    def test_crops_sparse_array_burst(self):
        from pcd import active_burst_window

        n = 1000
        signal = np.zeros(n)
        signal[300:550] = 1.0  # dense burst well above threshold
        start, end = active_burst_window(signal)
        assert 250 <= start <= 320
        assert 530 <= end <= 600
