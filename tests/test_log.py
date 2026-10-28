"""Developer log: one line per frame, no RF, schema unchanged."""

from __future__ import annotations

import logging

import numpy as np

from pcd import (
    CavitationRegime,
    FeedbackConfig,
    PCDFeedbackEngine,
    PCDReading,
    ReadingStatus,
    SCHEMA_VERSION,
    SignalParams,
    generate_signal,
)
from pcd.log import format_features, format_reading
from pcd.monitor import run_beside_trigger


def _reading(**overrides) -> PCDReading:
    base = dict(
        schema_version=SCHEMA_VERSION,
        frame_id=3,
        timestamp=0.4,
        status=ReadingStatus.OK,
        regime=CavitationRegime.STABLE,
        confidence=0.912,
        location_estimate=None,
        location_uncertainty=None,
        dose_proxy=0.01,
        latency_ms=1.24,
        stage_latency_ms={
            "features_ms": 0.8,
            "classify_ms": 0.11,
            "localize_ms": 0.0,
        },
    )
    base.update(overrides)
    return PCDReading(**base)


class TestFormat:
    def test_line_is_one_record_without_a_spectrum(self):
        line = format_reading(_reading(), reason="reading", detail="sub_amp=0.0123 snr=41.2 ci=0.041")
        assert "\n" not in line
        assert "frame=3" in line
        assert "t=0.400000" in line
        assert "status=ok" in line
        assert "regime=stable" in line
        assert "confidence=0.912" in line
        assert "reason=reading" in line
        assert "loc=null" in line
        assert "features_ms=0.80" in line
        assert "sub_amp=0.0123" in line
        assert "[" not in line

    def test_location_is_compact(self):
        line = format_reading(
            _reading(location_estimate=(0.001, 0.04)),
            reason="reading",
        )
        assert "loc=0.001,0.04" in line

    def test_infinite_snr_stays_a_token(self):
        class _Feat:
            subharmonic_amp = 0.01
            subharmonic_snr = float("inf")
            cavitation_index = 0.2

        assert format_features(_Feat()) == "sub_amp=0.0100 snr=inf ci=0.200"


class TestEngineLog:
    def test_ok_reading_is_info(self, caplog):
        caplog.set_level(logging.INFO, logger="pcd.reading")
        params = SignalParams.lifu(seed=1)
        _t, signal = generate_signal("stable", params)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=params.fs,
                f_drive=params.f_drive,
                localize_every_n=0,
                deadline_ms=5_000,
            )
        )
        reading = engine.process_frame(signal, trigger_timestamp=0.0)
        assert reading.status == ReadingStatus.OK
        lines = [r.getMessage() for r in caplog.records if r.name == "pcd.reading"]
        assert len(lines) == 1
        assert "reason=reading" in lines[0]
        assert "regime=stable" in lines[0]
        assert "sub_amp=" in lines[0]
        assert signal.nbytes > len(lines[0])

    def test_deadline_is_warning(self, caplog):
        caplog.set_level(logging.INFO, logger="pcd.reading")
        params = SignalParams.lifu(seed=0)
        _t, signal = generate_signal("none", params)
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=params.fs, f_drive=params.f_drive, localize_every_n=0, deadline_ms=0.0)
        )
        reading = engine.process_frame(signal, trigger_timestamp=1.5)
        assert reading.status == ReadingStatus.NO_READING
        record = next(r for r in caplog.records if r.name == "pcd.reading")
        assert record.levelno == logging.WARNING
        assert "reason=deadline" in record.getMessage()
        assert "t=1.500000" in record.getMessage()

    def test_fault_is_error_and_still_no_reading(self, caplog):
        caplog.set_level(logging.DEBUG, logger="pcd.reading")
        engine = PCDFeedbackEngine(FeedbackConfig(localize_every_n=0))
        reading = engine.process_frame(np.zeros((2, 2, 2)), trigger_timestamp=0.0)
        assert reading.status == ReadingStatus.NO_READING
        assert reading.regime == CavitationRegime.UNKNOWN
        record = next(r for r in caplog.records if r.name == "pcd.reading")
        assert record.levelno == logging.ERROR
        assert "reason=fault" in record.getMessage()
        assert "ValueError" in record.getMessage()
        assert record.exc_info is not None


class TestMonitorLog:
    def test_miss_is_warning_without_a_reading(self, caplog):
        caplog.set_level(logging.INFO, logger="pcd.monitor")
        params = SignalParams.lifu(seed=2)
        _t, signal = generate_signal("stable", params)
        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=params.fs,
                f_drive=params.f_drive,
                localize_every_n=0,
                deadline_ms=1_000,
            )
        )
        events = run_beside_trigger(
            engine,
            [signal, signal],
            pri_s=0.1,
            on_abort=lambda: None,
            busy_s=lambda _reading: 0.25,
        )
        assert events[1].missed is True
        lines = [r for r in caplog.records if r.name == "pcd.monitor"]
        assert len(lines) == 2
        assert lines[1].levelno == logging.WARNING
        assert "pulse=1" in lines[1].getMessage()
        assert "missed=true" in lines[1].getMessage()
        assert "regime=null" in lines[1].getMessage()
