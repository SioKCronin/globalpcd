"""
pcd.classifier
--------------
Threshold-based cavitation regime classifier using spectral features.

Classifies each signal window as:
  - 'none'      — no detectable cavitation
  - 'stable'    — stable/non-inertial cavitation (subharmonic dominant)
  - 'inertial'  — inertial cavitation (broadband dominant, high CI)
  - 'mixed'     — both stable and inertial regimes present

Classification logic
--------------------
  stable   → subharmonic_amp > subharmonic_threshold
  inertial → cavitation_index > ci_inertial_threshold
               (broadband/harmonic ratio; robust to normalisation)
  mixed    → both criteria met
  none     → neither criterion met

The cavitation index (CI) is the primary inertial discriminator because
absolute broadband level is strongly affected by signal normalisation,
whereas CI preserves the energy ratio between broadband and harmonic content.

Calibration
-----------
Thresholds below are calibrated against synthetic signals at 100 MHz
sample rate, 20 dB SNR, normalised to [-1, 1]. Scale appropriately
for experimental acquisition parameters.

References
----------
- Gyöngy & Coussios, IEEE UFFC 2010
- Haworth et al., JASA 2012
- Jensen et al., Ultrasound Med Biol 2016
"""

from dataclasses import dataclass
import math
from typing import Literal

from .features import SpectralFeatures

CavitationLabel = Literal["none", "stable", "inertial", "mixed"]


@dataclass
class ClassifierConfig:
    """
    Threshold configuration for cavitation regime classification.

    Attributes
    ----------
    subharmonic_threshold : float
        Minimum subharmonic amplitude (f/2 peak) to declare stable
        cavitation present. Units: normalised spectral amplitude.
    ci_inertial_threshold : float
        Minimum cavitation index (broadband_level / mean_harmonic)
        to declare inertial cavitation present. CI is dimensionless
        and more stable than absolute broadband level.
    """
    subharmonic_threshold: float = 0.005
    ci_inertial_threshold: float = 1.3    # separates noise (≤1.16) from inertial (≥1.49)


@dataclass
class ClassificationResult:
    label: CavitationLabel
    confidence: float               # 0–1, heuristic via sigmoid
    subharmonic_amp: float
    broadband_level: float
    cavitation_index: float
    notes: str


def classify(
    features: SpectralFeatures,
    config: ClassifierConfig | None = None,
) -> ClassificationResult:
    """
    Classify a PCD signal window into a cavitation regime.

    Parameters
    ----------
    features : SpectralFeatures
        Output from pcd.features.extract_features().
    config : ClassifierConfig, optional
        Threshold configuration. Defaults to ClassifierConfig().

    Returns
    -------
    ClassificationResult
    """
    if config is None:
        config = ClassifierConfig()

    stable_present   = features.subharmonic_amp     > config.subharmonic_threshold
    inertial_present = features.cavitation_index    > config.ci_inertial_threshold

    if stable_present and inertial_present:
        label: CavitationLabel = "mixed"
        conf_stable   = _sigmoid_confidence(
            features.subharmonic_amp / config.subharmonic_threshold
        )
        conf_inertial = _sigmoid_confidence(
            features.cavitation_index / config.ci_inertial_threshold
        )
        confidence = min(conf_stable, conf_inertial)
        notes = "Both subharmonic peak and elevated CI detected (mixed regime)."

    elif inertial_present:
        label = "inertial"
        confidence = _sigmoid_confidence(
            features.cavitation_index / config.ci_inertial_threshold
        )
        notes = (
            f"Cavitation index CI={features.cavitation_index:.3f} "
            f"exceeds threshold {config.ci_inertial_threshold}. "
            "Inertial collapse detected."
        )

    elif stable_present:
        label = "stable"
        confidence = _sigmoid_confidence(
            features.subharmonic_amp / config.subharmonic_threshold
        )
        notes = (
            f"Subharmonic amplitude={features.subharmonic_amp:.4f} "
            "at f/2. Stable oscillation regime."
        )

    else:
        label = "none"
        # Confidence = how far below both thresholds we are
        margin = 1.0 - max(
            features.subharmonic_amp / config.subharmonic_threshold,
            features.cavitation_index / config.ci_inertial_threshold,
        )
        confidence = max(0.0, min(1.0, margin))
        notes = "No significant cavitation activity detected."

    return ClassificationResult(
        label=label,
        confidence=float(confidence),
        subharmonic_amp=features.subharmonic_amp,
        broadband_level=features.broadband_level,
        cavitation_index=features.cavitation_index,
        notes=notes,
    )


def _sigmoid_confidence(ratio: float, k: float = 4.0) -> float:
    """Map a threshold ratio to a [0, 1] confidence via sigmoid."""
    return 1.0 / (1.0 + math.exp(-k * (ratio - 1.0)))
