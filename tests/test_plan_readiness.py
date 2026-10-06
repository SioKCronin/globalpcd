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

    @pytest.mark.parametrize("f_drive", [250e3, 500e3, 650e3])
    def test_lifu_regimes_across_seeds(self, f_drive):
        """Noise-only LIFU windows must not read as stable (was 23/30 at 500 kHz)."""
        n_seeds = 40
        labels = {"none": [], "stable": [], "inertial": []}
        for regime in labels:
            for seed in range(n_seeds):
                p = SignalParams.lifu(f_drive=f_drive, seed=seed)
                t, s = generate_signal(regime, p)
                labels[regime].append(
                    classify(extract_features(t, s, f_drive=p.f_drive)).label
                )
        false_pos = sum(lab != "none" for lab in labels["none"]) / n_seeds
        assert false_pos <= 0.05, f"noise false-positive rate {false_pos:.0%}"
        assert all(lab == "stable" for lab in labels["stable"])
        assert all(lab in {"inertial", "mixed"} for lab in labels["inertial"])

    def test_histotripsy_noise_across_seeds(self):
        n_seeds = 40
        false_pos = 0
        for seed in range(n_seeds):
            p = SignalParams(seed=seed)
            t, s = generate_signal("none", p)
            false_pos += classify(extract_features(t, s, f_drive=p.f_drive)).label != "none"
        assert false_pos / n_seeds <= 0.05

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


class TestSchemaVersioning:
    @staticmethod
    def _schema():
        path = Path(__file__).resolve().parents[1] / "docs" / "pcdreading.schema.json"
        return json.loads(path.read_text())

    @staticmethod
    def _payload():
        params = SignalParams.lifu(seed=1)
        _t, s = generate_signal("stable", params)
        engine = PCDFeedbackEngine(
            FeedbackConfig(fs=params.fs, f_drive=params.f_drive, localize_every_n=0)
        )
        return engine.process_frame(s, 0.0).to_dict()

    def test_current_reading_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.validate(self._payload(), self._schema())

    def test_minor_version_with_extra_field_validates(self):
        """Policy: 1.x adds optional fields; consumers ignore unknowns."""
        jsonschema = pytest.importorskip("jsonschema")
        payload = self._payload()
        payload["schema_version"] = "1.7.0"
        payload["future_field"] = 1.0
        jsonschema.validate(payload, self._schema())

    def test_1_0_reading_without_new_field_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        payload = self._payload()
        payload["schema_version"] = "1.0.0"
        payload.pop("location_frame_id")
        jsonschema.validate(payload, self._schema())

    def test_major_version_rejected(self):
        jsonschema = pytest.importorskip("jsonschema")
        payload = self._payload()
        payload["schema_version"] = "2.0.0"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, self._schema())
