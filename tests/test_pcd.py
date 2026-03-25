"""
Tests for pcd prototype toolkit.
Run with: pytest tests/
"""

import numpy as np
import pytest

from pcd import (
    generate_signal, SignalParams,
    extract_features,
    classify, ClassifierConfig,
    ArrayGeometry, simulate_array_signals, gcc_phat_map,
)


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

class TestSignalGeneration:
    def test_output_shapes_match(self):
        params = SignalParams(duration=10e-6)
        t, s = generate_signal("none", params)
        assert t.shape == s.shape
        assert len(t) == int(params.fs * params.duration)

    def test_all_regimes_normalised(self):
        for regime in ["none", "stable", "inertial"]:
            _, s = generate_signal(regime)
            assert np.max(np.abs(s)) <= 1.0 + 1e-9, \
                f"{regime} signal not normalised to [-1, 1]"

    def test_unknown_regime_raises(self):
        with pytest.raises(ValueError):
            generate_signal("unknown")          # type: ignore

    def test_reproducible_with_seed(self):
        p = SignalParams(seed=7)
        _, s1 = generate_signal("inertial", p)
        _, s2 = generate_signal("inertial", p)
        np.testing.assert_array_equal(s1, s2)

    def test_different_seeds_differ(self):
        _, s1 = generate_signal("stable", SignalParams(seed=1))
        _, s2 = generate_signal("stable", SignalParams(seed=2))
        assert not np.allclose(s1, s2)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

class TestFeatureExtraction:
    def test_stable_has_subharmonic(self):
        t, s = generate_signal("stable")
        feat = extract_features(t, s, f_drive=1e6)
        # Stable cavitation must have a subharmonic peak above noise
        assert feat.subharmonic_amp > 0.001

    def test_inertial_has_elevated_ci(self):
        t, s = generate_signal("inertial")
        feat = extract_features(t, s, f_drive=1e6)
        # Inertial regime has higher CI than stable (broadband dominates harmonics)
        t2, s2 = generate_signal("stable")
        feat2 = extract_features(t2, s2, f_drive=1e6)
        assert feat.cavitation_index > feat2.cavitation_index

    def test_freqs_and_psd_shape_match(self):
        t, s = generate_signal("stable")
        feat = extract_features(t, s)
        assert feat.freqs.shape == feat.psd.shape

    def test_harmonic_amps_length(self):
        t, s = generate_signal("stable")
        feat = extract_features(t, s, n_harmonics=4)
        assert len(feat.harmonic_amps) == 4

    def test_cavitation_index_positive(self):
        for regime in ["none", "stable", "inertial"]:
            t, s = generate_signal(regime)
            feat = extract_features(t, s)
            assert feat.cavitation_index >= 0


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TestClassifier:
    """
    Classification accuracy over 20 random seeds.
    Stable and inertial: 100% accuracy expected.
    None: ≥85% (a small fraction of pure-noise realisations have
          elevated CI by chance at 20 dB SNR).
    """

    def _accuracy(self, regime: str, n_seeds: int = 20) -> int:
        correct = 0
        for seed in range(n_seeds):
            p = SignalParams(seed=seed)
            t, s = generate_signal(regime, p)      # type: ignore
            feat = extract_features(t, s)
            result = classify(feat)
            if result.label == regime:
                correct += 1
        return correct

    def test_stable_accuracy(self):
        assert self._accuracy("stable") == 20

    def test_inertial_accuracy(self):
        assert self._accuracy("inertial") == 20

    def test_none_accuracy(self):
        assert self._accuracy("none") >= 17   # ≥85%

    def test_confidence_in_range(self):
        for regime in ["none", "stable", "inertial"]:
            t, s = generate_signal(regime)
            feat = extract_features(t, s)
            result = classify(feat)
            assert 0.0 <= result.confidence <= 1.0

    def test_custom_high_threshold_forces_none(self):
        config = ClassifierConfig(
            subharmonic_threshold=1e6,
            ci_inertial_threshold=1e6,
        )
        t, s = generate_signal("stable")
        feat = extract_features(t, s)
        result = classify(feat, config=config)
        assert result.label == "none"

    def test_result_has_notes(self):
        t, s = generate_signal("inertial")
        result = classify(extract_features(t, s))
        assert len(result.notes) > 0


# ---------------------------------------------------------------------------
# Beamformer
# ---------------------------------------------------------------------------

class TestBeamformer:
    def test_linear_array_shape(self):
        arr = ArrayGeometry.linear(n_elements=8)
        assert arr.element_positions.shape == (8, 2)

    def test_linear_array_centred(self):
        arr = ArrayGeometry.linear(n_elements=16)
        assert np.isclose(arr.element_positions[:, 0].mean(), 0.0, atol=1e-9)

    def test_linear_array_at_z_zero(self):
        arr = ArrayGeometry.linear()
        assert np.all(arr.element_positions[:, 1] == 0.0)

    def test_simulate_signals_shape(self):
        arr = ArrayGeometry.linear(n_elements=8)
        signals = simulate_array_signals(
            source_position=(0.0, 40e-3),
            array=arr,
            fs=50e6,
            duration=80e-6,
        )
        assert signals.shape[0] == 8

    def test_gcc_phat_peak_near_source(self):
        """GCC-PHAT map peak should be within 3 mm of the true source."""
        arr = ArrayGeometry.linear(n_elements=16)
        source = (0.0, 40e-3)
        signals = simulate_array_signals(
            source_position=source,
            array=arr,
            fs=50e6,
            duration=80e-6,
            snr_db=25,
            seed=0,
        )
        pam = gcc_phat_map(
            signals,
            fs=50e6,
            array=arr,
            x_range=(-12e-3, 12e-3),
            z_range=(25e-3, 55e-3),
            grid_points=60,
        )
        px, pz = pam.peak_location
        dist = np.sqrt((px - source[0]) ** 2 + (pz - source[1]) ** 2)
        assert dist < 3e-3, \
            f"PAM peak {dist*1000:.1f} mm from source (threshold 3 mm)"

    def test_gcc_phat_off_axis_source(self):
        """GCC-PHAT should localise an off-axis source within 3 mm."""
        arr = ArrayGeometry.linear(n_elements=16)
        source = (3e-3, 38e-3)
        signals = simulate_array_signals(
            source_position=source,
            array=arr,
            fs=50e6,
            duration=80e-6,
            snr_db=25,
            seed=5,
        )
        pam = gcc_phat_map(
            signals,
            fs=50e6,
            array=arr,
            x_range=(-12e-3, 12e-3),
            z_range=(25e-3, 55e-3),
            grid_points=60,
        )
        px, pz = pam.peak_location
        dist = np.sqrt((px - source[0]) ** 2 + (pz - source[1]) ** 2)
        assert dist < 3e-3, \
            f"Off-axis PAM peak {dist*1000:.1f} mm from source (threshold 3 mm)"

    def test_pam_result_has_db_map(self):
        arr = ArrayGeometry.linear(n_elements=8)
        signals = simulate_array_signals((0.0, 35e-3), arr, fs=50e6, duration=80e-6)
        pam = gcc_phat_map(signals, fs=50e6, array=arr,
                           x_range=(-10e-3, 10e-3), z_range=(20e-3, 50e-3),
                           grid_points=30)
        assert pam.intensity_db.shape == pam.intensity.shape
        assert np.max(pam.intensity_db) <= 0.1   # peak ≈ 0 dB
