# Changelog

All notable changes to globalPCD are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [0.1.1] — 2026-10-17

Review fixes ahead of platform outreach. Schema moves to **1.1.0** (additive).
Synthetic data only; research-only; not FDA-evaluated.

### Fixed

- **LIFU noise false positives.** Noise-only windows from `SignalParams.lifu()`
  classified as `stable` in 23/30 seeds (2/30 on the histotripsy preset). The
  amplitude gate (`subharmonic_amp > 0.005`) drifts with window length, and the
  shorter LIFU FFT pushed noise over it. `stable` now also requires the f/2 peak
  to clear its local noise floor (`SpectralFeatures.subharmonic_snr`,
  `ClassifierConfig.subharmonic_snr_threshold = 10`). Synthetic noise reaches
  ≤ ~5; stable windows ≥ ~40 across 250–650 kHz and the 1 MHz preset. Tests
  check rates across 40 seeds instead of one. On the mock controller, a
  ground-truth `none` frame that previously held as `stable` (confidence 0.93)
  now ramps as `none`.
- **Stale locations.** `none`/`unknown` frames no longer report or refresh the
  last location. Decimated carry-forward still applies to active frames, now
  labelled with `location_frame_id`.
- **Schema vs. versioning policy.** The JSON Schema rejected any 1.x reading with
  a new field (`additionalProperties: false`, `const: "1.0.0"`), contradicting the
  "minor = additive" policy. It now accepts additional properties and any `1.x.y`.
- **Inertial misses on short array bursts.** Frames 1–2 of a 6-frame
  `iter_array_frames(..., regimes="inertial")` stream classified as `none`.
  The synthetic inertial notch was a fixed ±30 kHz, narrower than one FFT
  bin on a ~20 µs burst (df ≈ 50 kHz), so a random broadband bin counted as
  a harmonic and CI fell below 1.3. The notch is now at least one bin wide.
  Direct histotripsy and LIFU windows are unchanged (their bins are already
  finer than 30 kHz).
- **WAV load peak-normalisation.** `load_hydrophone_file` divided by the file
  peak, so a quiet recording was stretched to full scale and absolute spectral
  amplitudes moved. Integer PCM is now scaled by the dtype full scale
  (int16 → 32768); float WAV is returned as stored. `write_hydrophone_wav`
  still peak-normalises on the way out so synthetics use the 16-bit range.

### Changed

- **Sensing never arms TX by default.** `OpenLIFUTriggerClock` is observe-only
  unless `allow_tx_start=True` (replaces `start_hardware`, which defaulted to
  `True`). Passing `trigger_json` without the opt-in raises. The example needs
  `--start-tx` to arm a connected device. **Breaking** for callers that relied on
  the old default.
- **2-D replay no longer guesses the shape.** `FileReplaySource` used to treat
  a 2-D array as one multi-channel frame when it had ≤256 rows and more
  columns than rows, and as stacked single-channel frames otherwise. A short
  single-channel session matches that first rule. 2-D files now require
  `layout="frames"` `(N_frames, N_samples)` or `layout="channels"`
  `(N_elements, N_samples)`. 3-D files stay `(N_frames, N_elements, N_samples)`.
  The example takes `--npy-layout`. **Breaking** for 2-D `.npy` callers.

### Added

- `PCDReading.location_frame_id` (schema 1.1.0, optional).
- `jsonschema` in the `dev` extra; schema forward-compat tests.
- CI runs pytest on Python 3.10, 3.11, 3.12, and 3.13.
- `docs/PCDREADING.md` records where `timestamp` comes from: the engine stores
  the caller's `trigger_timestamp`; `FeedbackSession` prefers
  `ReceiveFrame.trigger_timestamp` and otherwise uses `TriggerClock.wait()`,
  which for the software and OpenLIFU clocks is `time.perf_counter` pacing,
  not an observed TX edge. Built-in sources leave the frame timestamp unset.

### Upgrade

- Replace `start_hardware=True` with `allow_tx_start=True` only on a bench where
  arming TX is intentional. Omit it (the default) to stay observe-only. The
  example requires `--start-tx`.
- Readings now report `schema_version` **1.1.0**. Payloads from 1.0.0 still
  validate. 1.x consumers should ignore unknown fields. Use `location_frame_id`
  to tell a fresh location (`== frame_id`) from one carried forward under
  decimation; it is null when there is no location.
- A window that used to read `stable` on subharmonic amplitude alone can now
  read `none` if the f/2 peak does not clear the SNR gate.

### Not in this release

- No live OpenLIFU RF capture, no `globalpcd-openlifu` adapter, no tissue or
  bench calibration claims, no PyPI publish, no Zenodo DOI.

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

[0.1.1]: https://github.com/SioKCronin/globalpcd/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SioKCronin/globalpcd/releases/tag/v0.1.0
