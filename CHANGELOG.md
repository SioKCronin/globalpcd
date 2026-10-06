# Changelog

All notable changes to globalPCD are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-10-06

First review-ready release: a **cavitation safety monitor** for focused-ultrasound
controllers, with a versioned `PCDReading` contract. Synthetic data only;
research-only; not FDA-evaluated.

### Highlights

- **Contract:** `PCDFeedbackEngine` emits `PCDReading` (regime, confidence,
  optional location, measured latency). Sensing only — never chooses the next pulse.
- **Phase-1 ingest:** single-element hydrophone path (WAV / 1-D NumPy), matching
  OpenLIFU’s lack of a public receive array.
- **LIFU-band synthetics:** `SignalParams.lifu()` for 200–650 kHz neuromodulation-style tests.
- **Docs for platform engineers:** [`docs/PCDREADING.md`](docs/PCDREADING.md) and
  [`docs/pcdreading.schema.json`](docs/pcdreading.schema.json).
- **CI:** GitHub Actions runs the full pytest suite on every push/PR.

### Added

- `pcd.feedback` — `PCDReading`, `ReadingStatus`, `PCDFeedbackEngine` (pull + subscribe),
  per-stage latency, deadline → `no_reading`
- `pcd.hw` — `HydrophoneFileSource`, `FileReplaySource`, `SyntheticReceiveSource`,
  `SoftwarePRFClock`, optional `OpenLIFUTriggerClock` (TX start/stop; RF still from a receive source)
- `pcd.streams` — multi-channel synthetic array frames for localization tests
- Beamformers: GCC-PHAT, delay-and-sum, higher-order DMAS (optional / phase-2 localization)
- Examples: `hydrophone_ingest.py`, `mock_controller.py`, `openlifu_trigger_session.py`
- CONTRIBUTING: human contact required on PRs; free open-paper background links only
- Free background reading list in the README (arXiv / PMC / theses / preprints)

### Scope (what this release is not)

- No live OpenLIFU RF capture (SDK is TX/HV; PCD still needs an external hydrophone/DAQ)
- No `globalpcd-openlifu` adapter repo or in-tree interlock hook into openlifu-python
- No real-tissue / bench calibration claims
- No PyPI publish or Zenodo DOI yet (local / GitHub install: `pip install -e ".[dev]"`)

### Try it

```bash
git clone https://github.com/SioKCronin/globalpcd.git
cd globalpcd
pip install -e ".[dev]"
pytest tests/ -q
python examples/hydrophone_ingest.py
python examples/mock_controller.py
```

### Upgrade / adoption notes

- Schema version: **`1.0.0`** (`SCHEMA_VERSION` / `PCDReading.to_dict()`).
- Controllers should treat `no_reading` as fail-safe hold; weight `ok`/`degraded` by `confidence`.
- Default story for OpenLIFU partners: single-channel safety monitor; array localization is optional later.

[0.1.0]: https://github.com/SioKCronin/globalpcd/releases/tag/v0.1.0
