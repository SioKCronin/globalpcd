# globalPCD

[![tests](https://github.com/SioKCronin/globalpcd/actions/workflows/tests.yml/badge.svg)](https://github.com/SioKCronin/globalpcd/actions/workflows/tests.yml)

**Cavitation safety monitor for focused-ultrasound controllers.** MIT-licensed, vendor-neutral.

OpenLIFU (and similar platforms) can plan and deliver ultrasound, but they do
not hear what happens in tissue. globalPCD consumes receive-channel RF and
emits a versioned [`PCDReading`](docs/PCDREADING.md): no / stable / inertial
cavitation, how sure, optional location, measured latency. It **never** chooses
the next pulse.

For neuromodulation, cavitation is a hazard to avoid. A high-confidence
`inertial` reading is meant as an interlock or step-down input beside existing
mechanical-index limits — research-only, not FDA-evaluated. Histotripsy-style
dosing and array localization remain in the toolkit as a later path.

## Install

From the repository root (`globalpcd`):

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

Release notes for the current milestone: [`CHANGELOG.md`](CHANGELOG.md).

## Quick start (single-element, LIFU band)

This is the first integration shape: one hydrophone-like channel, no array.

```python
from pcd import FeedbackConfig, PCDFeedbackEngine, SignalParams, generate_signal

params = SignalParams.lifu(f_drive=500e3)  # 200–650 kHz neuromod band
_t, rf = generate_signal("inertial", params)
engine = PCDFeedbackEngine(
    FeedbackConfig(fs=params.fs, f_drive=params.f_drive, localize_every_n=0)
)
reading = engine.process_frame(rf, trigger_timestamp=0.0)
print(reading.status, reading.regime, reading.confidence, f"{reading.latency_ms:.2f} ms")
```

File ingest (WAV or 1-D NumPy) as if from a DAQ:

```bash
python examples/hydrophone_ingest.py
```

Contract for platform engineers: [`docs/PCDREADING.md`](docs/PCDREADING.md)
and [`docs/pcdreading.schema.json`](docs/pcdreading.schema.json).

Mocked controller (ramp / hold / reduce-pressure from readings only):

```bash
python examples/mock_controller.py
```

## Package layout

| Module | Role |
|--------|------|
| `pcd.signals` | Synthetic RF (`none` / `stable` / `inertial`); `SignalParams.lifu()` |
| `pcd.features` | Spectral features (subharmonic, CI, dose proxies) |
| `pcd.classifier` | Threshold-based regime classification (with confidence) |
| `pcd.beamformer` | Optional array mapping (GCC-PHAT, DAS, HO-DMAS) — phase 2 |
| `pcd.feedback` | `PCDFeedbackEngine` → `PCDReading` |
| `pcd.hw` | Hydrophone file ingest, TX-trigger clock, synthetic / `.npy` sources |

Prototype copies and a browser visualiser live under [`files/`](files/README.md)
([`files/pcd_viz.html`](files/pcd_viz.html)).

## Hardware path (OpenLIFU)

The public OpenLIFU SDK drives **transmit** (TX7332 + HV), not a receive array.
Phase 1 is a single PCD hydrophone + DAQ feeding this engine. Optional:
pace frames alongside an OpenLIFU TX module while RF still comes from a file or
synthetic source (`examples/openlifu_trigger_session.py`).

`OpenLIFUTriggerClock` is **observe-only by default**: it never arms or starts
the transmitter. Arming TX is an actuation decision for the therapy platform;
pass `allow_tx_start=True` (or `--start-tx` in the example) only on a bench.

`pip install -e ".[openlifu]"` is optional and not required for tests.

## Collaboration

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Sensing stays here; pulse policy
stays with the platform. Real-tissue validation is welcome and is not claimed
by the synthetic default path.

## Free background reading

Open full texts only (arXiv, PMC, theses, preprints) — no paywalled citations.

| Topic | Free paper |
|-------|------------|
| Passive cavitation mapping overview | [Gyöngy Oxford thesis](https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d) |
| Stable vs inertial / PCI monitoring | [PMC4526372](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4526372/) |
| Angular-spectrum PAM | [PMC5565398](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5565398/) |
| PAM beamforming (arXiv) | [2412.02413](https://arxiv.org/abs/2412.02413), [2412.02327](https://arxiv.org/abs/2412.02327), [2601.07356](https://arxiv.org/abs/2601.07356) |
| HO-DMAS for PCM (preprint) | [SSRN 5029537](https://ssrn.com/abstract=5029537) |
| Microbubble acoustic emissions | [arXiv 2512.22292](https://arxiv.org/abs/2512.22292) |

## License

[MIT License](LICENSE).

## Citation

Cronin, S. K. (2025). globalPCD: Passive cavitation detection prototype toolkit (Python). https://github.com/SioKCronin/globalPCD

```bibtex
@software{globalpcd2025,
  author = {Cronin, Siobhan K},
  title = {{globalPCD}: Passive cavitation detection toolkit},
  year = {2025},
  url = {https://github.com/SioKCronin/globalPCD},
  note = {PCDReading contract, synthetic PCD, spectral classification, optional PAM},
}
```

Machine-readable: [`CITATION.cff`](CITATION.cff).
