"""Partnership-plan repo-readiness: LIFU preset, hydrophone ingest, schema."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pcd import (
    FeedbackConfig,
    PCDFeedbackEngine,
    SCHEMA_VERSION,
    SignalParams,
    classify,
    extract_features,
    generate_signal,
)
from pcd.hw import HydrophoneFileSource, write_hydrophone_wav


class TestLifuPreset:
    def test_drive_band(self):
        p = SignalParams.lifu()
        assert p.f_drive == 500e3
        assert 200e3 <= p.f_drive <= 650e3
        assert p.fs == 10e6

    def test_rejects_histotripsy_mhz(self):
        with pytest.raises(ValueError, match="200"):
            SignalParams.lifu(f_drive=1e6)

    def test_inertial_classifies_in_lifu_band(self):
        params = SignalParams.lifu(seed=0)
        t, s = generate_signal("inertial", params)
        feat = extract_features(t, s, f_drive=params.f_drive)
        result = classify(feat)
        assert result.label in {"inertial", "mixed"}


class TestHydrophoneIngest:
    def test_wav_roundtrip_into_engine(self, tmp_path: Path):
        params = SignalParams.lifu(seed=3)
        _t, signal = generate_signal("stable", params)
        wav = tmp_path / "hydro.wav"
        write_hydrophone_wav(wav, signal, params.fs)

        src = HydrophoneFileSource(wav)
        frame = src.next_frame()
        assert frame is not None
        assert src.fs == params.fs
        assert src.next_frame() is None

        engine = PCDFeedbackEngine(
            FeedbackConfig(
                fs=params.fs,
                f_drive=params.f_drive,
                localize_every_n=0,
                deadline_ms=5_000,
            )
        )
        reading = engine.process_frame(frame.channel_data, trigger_timestamp=0.0)
        payload = reading.to_dict()
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["location_estimate"] is None
        assert payload["regime"] in {"none", "stable", "inertial", "mixed", "unknown"}
        assert payload["latency_ms"] >= 0.0

    def test_npy_requires_fs(self, tmp_path: Path):
        path = tmp_path / "rf.npy"
        np.save(path, np.zeros(64))
        with pytest.raises(ValueError, match="fs"):
            HydrophoneFileSource(path)


class TestReadingSchema:
    def test_to_dict_matches_required_keys(self):
        schema_path = (
            Path(__file__).resolve().parents[1] / "docs" / "pcdreading.schema.json"
        )
        schema = json.loads(schema_path.read_text())
        params = SignalParams.lifu(seed=1)
        _t, s = generate_signal("none", params)
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=params.fs, f_drive=params.f_drive, localize_every_n=0)
        )
        payload = engine.process_frame(s, 0.0).to_dict()
        for key in schema["required"]:
            assert key in payload
        assert payload["status"] in schema["properties"]["status"]["enum"]
        assert payload["regime"] in schema["properties"]["regime"]["enum"]
