"""
globalPCD — Passive cavitation detection (PCD) prototype toolkit.

Synthetic signals, spectral features, regime classification, passive
acoustic mapping (GCC-PHAT, DAS, higher-order DMAS), and a feedback
layer that emits structured PCDReading values for a therapy controller.

Background links use free papers only (arXiv / PMC / theses / preprints);
see the repository README and each module's ``Context (free papers)`` block.
"""

from .signals import (
    SignalParams,
    generate_signal,
    iter_signals,
)
from .features import SpectralFeatures, active_burst_window, extract_features
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
from .feedback import (
    SCHEMA_VERSION,
    CavitationRegime,
    FeedbackConfig,
    PCDFeedbackEngine,
    PCDReading,
    ReadingStatus,
)
from .streams import iter_array_frames
from .hw import (
    FeedbackSession,
    FileReplaySource,
    HydrophoneFileSource,
    OpenLIFUTriggerClock,
    ReceiveFrame,
    SoftwarePRFClock,
    SyntheticReceiveSource,
    load_hydrophone_file,
    try_openlifu_tx,
    write_hydrophone_wav,
)

__all__ = [
    "SignalParams",
    "generate_signal",
    "iter_signals",
    "SpectralFeatures",
    "active_burst_window",
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
    "SCHEMA_VERSION",
    "CavitationRegime",
    "FeedbackConfig",
    "PCDFeedbackEngine",
    "PCDReading",
    "ReadingStatus",
    "iter_array_frames",
    "FeedbackSession",
    "FileReplaySource",
    "HydrophoneFileSource",
    "OpenLIFUTriggerClock",
    "ReceiveFrame",
    "SoftwarePRFClock",
    "SyntheticReceiveSource",
    "load_hydrophone_file",
    "try_openlifu_tx",
    "write_hydrophone_wav",
]

__version__ = "0.1.1"
__license__ = "MIT"
