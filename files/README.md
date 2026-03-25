# pcd-proto

**Passive Cavitation Detection — software prototype**

> **Installable package:** from the repository root, run `pip install -e ".[dev]"` and `import pcd` (see root [`README.md`](../README.md)). Module sources live in [`pcd/`](../pcd/); this `files/` folder keeps the long-form documentation and `pcd_viz.html`.

A Python toolkit for simulating, analysing, and spatially localising
acoustic emissions from histotripsy bubble clouds, built as a
citizen-science contribution toward solving the open problem of
real-time treatment monitoring.

---

## What this is

Histotripsy is a non-invasive tissue ablation technique that uses
high-intensity focused ultrasound to mechanically destroy tissue via
cavitation — the rapid formation and violent collapse of microscopic
bubbles. It is FDA-approved for liver cancer and is under active
investigation for pancreatic cancer, cardiac ablation, and other
applications.

**The unsolved problem this addresses:** there is currently no robust,
real-time, closed-loop system for verifying that bubble cloud activity
is occurring at the intended target and nowhere else during treatment.
Passive cavitation detection (PCD) — listening to the acoustic
emissions of the bubble cloud with a separate receive array — is the
leading candidate for solving this, but the signal processing and
source localisation pipeline is still an open research area.

This prototype implements the full pipeline in pure Python, using only
synthetic data, so it can be explored and extended without hardware.

---

## The physics in two paragraphs

During histotripsy, the therapy transducer fires short, high-pressure
pulses (0.3–3 MHz, negative pressures up to 25 MPa). The bubble cloud
that forms emits its own acoustic energy, which a passive receiver can
detect.

Three distinct regimes produce characteristically different spectra.
**Stable cavitation** produces periodic oscillations and emits at the
drive frequency, its harmonics, and — critically — the subharmonic at
f/2 and ultraharmonics at 3f/2, 5f/2. **Inertial cavitation** involves
violent bubble collapse and produces broadband noise across the entire
spectrum. The ratio of broadband-to-harmonic energy (the cavitation
index, CI) cleanly separates the two regimes. **No cavitation** shows
only the noise floor.

---

## Modules

```
pcd/
├── signals.py      Synthetic PCD signal generation
│                   Three regimes: none / stable / inertial
│                   Parameterised by drive frequency, SNR, broadband boost
│
├── features.py     Spectral feature extraction
│                   Subharmonic amplitude (f/2 peak)
│                   Ultraharmonic amplitude (3f/2)
│                   Broadband noise level (RMS, harmonic-notched band)
│                   Cavitation index CI = broadband / mean_harmonic
│                   Stable/inertial dose proxies (SCD, ICD)
│
├── classifier.py   Threshold-based regime classifier
│                   Stable:   subharmonic_amp > threshold
│                   Inertial: CI > ci_threshold  (robust to normalisation)
│                   Mixed:    both criteria met
│                   Returns label + sigmoid confidence score
│
└── beamformer.py   Spatial source localisation
                    gcc_phat_map()  — GCC-PHAT TDOA grid search (recommended)
                    delay_and_sum() — classic DAS (included for comparison)
                    simulate_array_signals() — multi-element signal simulator
                    ArrayGeometry   — linear array geometry helper
```

---

## Quick start

```python
from pcd import (
    generate_signal, SignalParams,
    extract_features,
    classify,
    ArrayGeometry, simulate_array_signals, gcc_phat_map,
)

# 1. Generate a synthetic inertial cavitation signal
params = SignalParams(fs=100e6, duration=50e-6, f_drive=1e6, snr_db=20)
t, signal = generate_signal("inertial", params)

# 2. Extract spectral features
features = extract_features(t, signal, f_drive=1e6)
print(f"Subharmonic amp: {features.subharmonic_amp:.4f}")
print(f"Cavitation index: {features.cavitation_index:.4f}")

# 3. Classify the regime
result = classify(features)
print(f"Label: {result.label}  Confidence: {result.confidence:.0%}")
print(f"Notes: {result.notes}")

# 4. Localise a cavitation source with a 16-element passive array
array = ArrayGeometry.linear(n_elements=16, pitch=1.5e-3)

# Simulate signals received at each element from a source at (2 mm, 40 mm)
signals = simulate_array_signals(
    source_position=(2e-3, 40e-3),
    array=array,
    fs=50e6,
    duration=80e-6,
    snr_db=25,
)

# Reconstruct the passive acoustic map
pam = gcc_phat_map(
    signals,
    fs=50e6,
    array=array,
    x_range=(-12e-3, 12e-3),
    z_range=(22e-3, 52e-3),
    grid_points=60,
)
print(f"Detected source: x={pam.peak_location[0]*1e3:.1f} mm, "
      f"z={pam.peak_location[1]*1e3:.1f} mm")
```

---

## Algorithms

### Spectral classification

The key insight is that **the cavitation index (CI)** — the ratio of
broadband RMS energy to mean harmonic amplitude — is the most robust
discriminator for inertial cavitation. Absolute broadband level
depends on signal normalisation; CI does not.

| Feature | Stable | Inertial | None |
|---|---|---|---|
| Subharmonic f/2 | ↑ high | low | low |
| Broadband floor | low | ↑ high | low |
| CI = broadband/harmonic | low (~0.01) | ↑ high (~1.6) | medium (~1.0) |

The classifier uses:
- `subharmonic_amp > 0.005` → stable present
- `cavitation_index > 1.3` → inertial present

Both thresholds are calibrated against synthetic signals at 100 MHz,
20 dB SNR, normalised to [-1, 1]. Scale for your acquisition setup.

### GCC-PHAT source localisation

Generalised Cross-Correlation with PHAse Transform. For each element
pair (element_i, reference element):

1. Compute cross-spectrum: `R = FFT(signal_i) * conj(FFT(signal_ref))`
2. Apply PHAT weighting: `R_phat = R / |R|` (phase-only, amplitude-flat)
3. TDOA = lag at peak of `IFFT(R_phat)`

Then grid-search for the spatial point whose predicted TDOAs best
explain the measured TDOAs (minimum squared residual).

GCC-PHAT is preferred over classic delay-and-sum for broadband
inertial cavitation signals because phase normalisation removes
amplitude bias and produces sharper TDOA peaks.

**Localisation accuracy (synthetic, 16 elements, 25 dB SNR):**
sub-millimetre error across test sources at 30–45 mm depth.

---

## The open problems this could contribute to

This prototype is scoped to lay groundwork for three research gaps:

**1. Real-time treatment monitoring**
The full clinical pipeline needs closed-loop feedback: detect where
cavitation is occurring, verify it matches the intended target, halt
if off-target activity is detected. This prototype implements the
detection and localisation legs. The feedback control loop is missing.

**2. Cavitation dose quantification**
There is no validated "cavitation dose" metric analogous to thermal
dose in HIFU. The ICD (inertial cavitation dose) and SCD (stable
cavitation dose) proxies implemented here are energy integrals over
time — but their correlation with actual tissue destruction extent is
not well characterised.

**3. Broadband source imaging**
Classic delay-and-sum degrades for broadband inertial emissions. The
GCC-PHAT approach improves this. More sophisticated methods —
minimum-variance beamforming, time-reversal, angular spectrum — could
further improve spatial resolution and contrast.

---

## Installation

```bash
git clone https://github.com/your-username/pcd-proto
cd pcd-proto
pip install -r requirements.txt
```

**Requirements:** `numpy`, `scipy`

**Dev requirements:** `pytest`

---

## Tests

```bash
pytest tests/
```

23 tests covering signal generation, feature extraction, classification
accuracy (20 seeds per regime), and beamformer localisation.

---

## Interactive visualisation

Open `pcd_viz.html` in any browser. Shows:
- Time-domain RF signal for each cavitation regime
- Power spectral density with annotated f/2, f₀, 3f/2 markers
- Regime classification badge and confidence
- Passive acoustic map with GCC-PHAT source localisation

No server required — all data is pre-computed and embedded.

---

## Repository context

This prototype was developed as a citizen-science contribution
aimed at opening collaboration with histotripsy research groups
working on the treatment monitoring problem.

Groups doing active work in this space:
- University of Michigan (Xu / Hall group) — intrinsic threshold histotripsy
- University of Washington (Bailey / Crum group) — cavitation physics
- University of Michigan HistoSonics spinout

If you work in therapeutic ultrasound and find this useful or see ways
to extend it toward real experimental data, get in touch.

---

## Citation

See the repository root [`README.md`](../README.md) for BibTeX, plain text, and [`CITATION.cff`](../CITATION.cff).

```
Siobhan K Cronin, globalPCD (2025)
GitHub: https://github.com/SioKCronin/globalPCD
```

---

## Licence

This project is released under the [MIT License](../LICENSE).
