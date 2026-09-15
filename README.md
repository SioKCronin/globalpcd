# globalPCD

**Passive cavitation detection (PCD)** — Python toolkit for simulating, analysing, and spatially localising acoustic emissions from histotripsy bubble clouds.

The hard part is not detecting that cavitation exists, but rather knowing, in real time, **where** it is and **what kind** it is. Therapy pulses, tissue clutter, and bubble clouds all radiate into the same receive array. Stable and inertial regimes overlap spectrally, and on diagnostic linear arrays, conventional delay-and-sum maps are axially blurred with high sidelobes, while sharper adaptive beamformers are often too slow for closed-loop monitoring. 

## Free background reading

This repo links open full texts only (arXiv, PMC, theses, preprints) — no paywalled journal citations.

| Topic | Free paper |
|-------|------------|
| Passive cavitation mapping overview | [Gyöngy Oxford thesis](https://ora.ox.ac.uk/objects/uuid:af6f3c5a-bec5-4378-a617-c89d2b16d95d) |
| Stable vs inertial / PCI monitoring | [PMC4526372](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4526372/) |
| Angular-spectrum PAM | [PMC5565398](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5565398/) |
| PAM beamforming (arXiv) | [2412.02413](https://arxiv.org/abs/2412.02413), [2412.02327](https://arxiv.org/abs/2412.02327), [2601.07356](https://arxiv.org/abs/2601.07356) |
| HO-DMAS for PCM (preprint) | [SSRN 5029537](https://ssrn.com/abstract=5029537) |
| Microbubble acoustic emissions | [arXiv 2512.22292](https://arxiv.org/abs/2512.22292) |

## Install

```bash
cd globalPCD
pip install -e ".[dev]"
```

## Run tests

```bash
pytest tests/ -v
```

## Package layout

| Module | Role |
|--------|------|
| `pcd.signals` | Synthetic RF time-domain signals (`none`, `stable`, `inertial`); `iter_signals` stream |
| `pcd.features` | Spectral features (subharmonic, CI, dose proxies) |
| `pcd.classifier` | Threshold-based regime classification (with confidence) |
| `pcd.beamformer` | `gcc_phat_map`, `delay_and_sum`, `delay_multiply_and_sum` (HO-DMAS), `simulate_array_signals` |
| `pcd.feedback` | Live/synthetic feedback layer → `PCDReading` for a therapy controller |
| `pcd.streams` | Multi-channel synthetic frame stream for localization tests |

## Full documentation

See [`files/README.md`](files/README.md) for physics background, API examples, and the HTML visualiser [`files/pcd_viz.html`](files/pcd_viz.html).

The original prototype sources remain under `files/` for reference; the installable package lives in `pcd/`.

## Quick example

```python
from pcd import generate_signal, SignalParams, extract_features, classify

t, s = generate_signal("stable", SignalParams())
feat = extract_features(t, s, f_drive=1e6)
result = classify(feat)
print(result.label, result.notes)
```

Higher-order DMAS mapping (default order 5; open preprint https://ssrn.com/abstract=5029537):

```python
from pcd import ArrayGeometry, simulate_array_signals, delay_multiply_and_sum

array = ArrayGeometry.linear(n_elements=16)
signals = simulate_array_signals((0.0, 40e-3), array, fs=50e6, snr_db=25)
pam = delay_multiply_and_sum(signals, fs=50e6, array=array, order=5)
print(pam.peak_location)
```

## Feedback layer

`pcd.feedback` sits between a receive array (or synthetic stream) and a therapy controller. It emits structured `PCDReading` values — regime, confidence, optional location, measured latency — and never chooses the next pulse.

```python
from pcd import FeedbackConfig, PCDFeedbackEngine, iter_signals, SignalParams

engine = PCDFeedbackEngine(FeedbackConfig(fs=20e6, localize_every_n=0))
for frame_id, t, signal in iter_signals("inertial", SignalParams(fs=20e6), n_frames=3):
    reading = engine.process_frame(signal, trigger_timestamp=frame_id * 0.01)
    print(reading.status, reading.regime, reading.confidence, f"{reading.latency_ms:.2f} ms")
```

Mocked controller demo (ramp / hold / reduce-pressure from readings only):

```bash
.venv/bin/python examples/mock_controller.py
```

Also: `scripts/feedback_demo.py` for pull + push path smoke tests.

## Collaboration

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Short version: this layer is meant to
be adoptable by any therapy controller — OpenLIFU included — without owning
pulse policy. Sensing stays here; actuation stays with the platform. Real-tissue
validation is welcome as collaboration and is intentionally not claimed by the
synthetic default path.

## License

This project is licensed under the [MIT License](LICENSE).

## Citation

If you use globalPCD in research or publications, please cite the software as:

**Plain text**

Cronin, S. K. (2025). globalPCD: Passive cavitation detection prototype toolkit (Python). https://github.com/SioKCronin/globalPCD

**BibTeX**

```bibtex
@software{globalpcd2025,
  author = {Cronin, Siobhan K},
  title = {{globalPCD}: Passive cavitation detection toolkit},
  year = {2025},
  url = {https://github.com/SioKCronin/globalPCD},
  note = {Synthetic PCD signals, spectral features, regime classification, GCC-PHAT passive mapping},
}
```

A machine-readable citation file is also provided as [`CITATION.cff`](CITATION.cff) (supported by GitHub and Zenodo).
