"""
globalPCD — Passive cavitation detection (PCD) prototype toolkit.

Synthetic signals, spectral features, regime classification, and passive
acoustic mapping (GCC-PHAT, DAS, higher-order DMAS) for histotripsy-related
research.

Background links use free papers only (arXiv / PMC / theses / preprints);
see the repository README and each module's ``Context (free papers)`` block.
"""

from .signals import (
    CavitationRegime,
    SignalParams,
    generate_signal,
)
from .features import SpectralFeatures, extract_features
from .classifier import (
    CavitationLabel,
    ClassificationResult,
    ClassifierConfig,
    classify,
)
from .beamformer import (
    ArrayGeometry,
    PAMResult,
    delay_and_sum,
    delay_multiply_and_sum,
    gcc_phat_map,
    simulate_array_signals,
)

__all__ = [
    "CavitationRegime",
    "SignalParams",
    "generate_signal",
    "SpectralFeatures",
    "extract_features",
    "CavitationLabel",
    "ClassificationResult",
    "ClassifierConfig",
    "classify",
    "ArrayGeometry",
    "PAMResult",
    "delay_and_sum",
    "delay_multiply_and_sum",
    "gcc_phat_map",
    "simulate_array_signals",
]

__version__ = "0.1.0"
__license__ = "MIT"
