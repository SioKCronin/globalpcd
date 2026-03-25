# globalPCD

**Passive cavitation detection (PCD)** — Python toolkit for simulating, analysing, and spatially localising acoustic emissions from histotripsy bubble clouds (synthetic data only).

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
| `pcd.signals` | Synthetic RF time-domain signals (`none`, `stable`, `inertial`) |
| `pcd.features` | Spectral features (subharmonic, CI, dose proxies) |
| `pcd.classifier` | Threshold-based regime classification |
| `pcd.beamformer` | `gcc_phat_map`, `delay_and_sum`, `simulate_array_signals` |

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
