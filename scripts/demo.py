#!/usr/bin/env python3
"""
globalPCD local demo
--------------------
Generates figures for the full synthetic PCD pipeline:

1. Regime classification (none / stable / inertial)
2. Passive acoustic maps: GCC-PHAT, DAS, and HO-DMAS (order 5)

Run from the repo root:

    .venv/bin/python scripts/demo.py

Outputs land in ``demo_output/``. Open ``files/pcd_viz.html`` in a browser
for the interactive visualiser.

Free background papers are listed in the repository README (arXiv / PMC /
theses / preprints only — no paywalled citations).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from pcd import (
    ArrayGeometry,
    SignalParams,
    classify,
    delay_and_sum,
    delay_multiply_and_sum,
    extract_features,
    gcc_phat_map,
    generate_signal,
    simulate_array_signals,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_output"
FS = 50e6
F_DRIVE = 1e6


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#0b1018",
            "axes.facecolor": "#111827",
            "axes.edgecolor": "#334155",
            "axes.labelcolor": "#cbd5e1",
            "text.color": "#e2e8f0",
            "xtick.color": "#94a3b8",
            "ytick.color": "#94a3b8",
            "grid.color": "#1e293b",
            "font.family": "sans-serif",
            "font.size": 10,
        }
    )


def demo_regimes() -> Path:
    """Time domain + PSD + classifier badge for each regime."""
    regimes = ("none", "stable", "inertial")
    colors = {"none": "#60a5fa", "stable": "#34d399", "inertial": "#f87171"}

    fig, axes = plt.subplots(3, 2, figsize=(11, 8), constrained_layout=True)
    fig.suptitle("globalPCD · cavitation regime classification", fontsize=14, fontweight="bold")

    for row, regime in enumerate(regimes):
        params = SignalParams(fs=FS, duration=40e-6, f_drive=F_DRIVE, snr_db=20, seed=7)
        t, s = generate_signal(regime, params)
        feat = extract_features(t, s, f_drive=F_DRIVE)
        result = classify(feat)

        ax_t, ax_f = axes[row]
        ax_t.plot(t * 1e6, s, color=colors[regime], lw=0.8)
        ax_t.set_ylabel("Amplitude")
        ax_t.set_xlim(t[0] * 1e6, t[-1] * 1e6)
        ax_t.grid(True, alpha=0.35)
        ax_t.set_title(
            f"{regime.upper()}  →  {result.label.upper()}  ({result.confidence:.0%} conf)",
            color=colors[regime],
            loc="left",
            fontsize=11,
        )

        ax_f.semilogy(feat.freqs / 1e6, feat.psd + 1e-18, color=colors[regime], lw=0.9)
        ax_f.set_xlim(0, 5)
        ymin, ymax = ax_f.get_ylim()
        for mult, name in ((0.5, "f/2"), (1.0, "f₀"), (1.5, "3f/2")):
            ax_f.axvline(F_DRIVE * mult / 1e6, color="#64748b", ls="--", lw=0.7, alpha=0.8)
            ax_f.text(
                F_DRIVE * mult / 1e6,
                ymax * 0.5,
                name,
                color="#94a3b8",
                fontsize=8,
                ha="center",
                va="bottom",
            )
        ax_f.set_ylabel("PSD")
        ax_f.grid(True, alpha=0.35)
        ax_f.text(
            0.98,
            0.92,
            f"CI={feat.cavitation_index:.2f}\nsub={feat.subharmonic_amp:.3f}",
            transform=ax_f.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color="#94a3b8",
            family="monospace",
        )

    axes[-1, 0].set_xlabel("Time (µs)")
    axes[-1, 1].set_xlabel("Frequency (MHz)")
    path = OUT / "01_regimes.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def demo_pam() -> Path:
    """Compare GCC-PHAT, DAS, and HO-DMAS maps for one inertial source."""
    array = ArrayGeometry.linear(n_elements=16, pitch=1.5e-3)
    source = (0.0, 40e-3)
    signals = simulate_array_signals(
        source_position=source,
        array=array,
        fs=FS,
        duration=80e-6,
        regime="inertial",
        snr_db=25,
        seed=0,
    )

    grid = dict(
        x_range=(-12e-3, 12e-3),
        z_range=(25e-3, 55e-3),
        grid_points=41,
    )
    maps = {
        "GCC-PHAT": gcc_phat_map(signals, fs=FS, array=array, **grid),
        "DAS": delay_and_sum(signals, fs=FS, array=array, **grid),
        "DMAS-5": delay_multiply_and_sum(
            signals, fs=FS, array=array, order=5, upsample=False, **grid
        ),
    }

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), constrained_layout=True)
    fig.suptitle(
        "Passive acoustic mapping · inertial source at (0, 40) mm",
        fontsize=13,
        fontweight="bold",
    )

    for ax, (name, pam) in zip(axes, maps.items()):
        x_mm = pam.x_axis * 1e3
        z_mm = pam.z_axis * 1e3
        extent = [x_mm[0], x_mm[-1], z_mm[-1], z_mm[0]]
        im = ax.imshow(
            pam.intensity_db,
            extent=extent,
            aspect="auto",
            cmap="magma",
            vmin=-30,
            vmax=0,
        )
        ax.plot(source[0] * 1e3, source[1] * 1e3, "c+", ms=12, mew=2, label="true")
        ax.plot(
            pam.peak_location[0] * 1e3,
            pam.peak_location[1] * 1e3,
            "w.",
            ms=10,
            label="peak",
        )
        err = np.hypot(
            pam.peak_location[0] - source[0],
            pam.peak_location[1] - source[1],
        )
        ax.set_title(f"{name}\npeak err = {err * 1e3:.1f} mm", fontsize=11)
        ax.set_xlabel("x (mm)")
        ax.set_ylabel("z (mm)")
        ax.legend(loc="lower right", fontsize=8, framealpha=0.35)

    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.85, label="Intensity (dB)")
    path = OUT / "02_pam_comparison.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    _style()
    OUT.mkdir(exist_ok=True)
    print(f"Writing demo figures to {OUT}/")
    p1 = demo_regimes()
    print(f"  ✓ {p1.name}")
    p2 = demo_pam()
    print(f"  ✓ {p2.name}")
    print()
    print("Interactive visualiser (no server needed):")
    print(f"  open {ROOT / 'files' / 'pcd_viz.html'}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
