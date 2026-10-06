# Contributing

Thanks for looking at globalPCD. It is an MIT-licensed cavitation **safety
monitor** for focused-ultrasound controllers (OpenLIFU included): emit a
versioned `PCDReading`, never choose the next pulse. Histotripsy dosing
research is in the toolkit but is not the lead use case.

This software is research-only and not FDA-evaluated.

## Human contact required

We only review pull requests (and issue threads that need back-and-forth) when
there is a **reachable human** who can answer clarifying questions about the
change — design intent, test evidence, and how it was validated.

Automated or unattended agent-only PRs with no human contact path will be
closed. If an agent helped write the code, that is fine; name the human
maintainer who will respond on the PR.

## What this repo is (and is not)

- **Is:** synthetic-data toolkit + a `PCDReading` contract a therapy controller
  can call or subscribe to (single-element ingest first; array localization
  optional).
- **Is not:** a pulse sequencer, a treatment planner, an FDA-cleared safety
  claim, or a predictor of lesion completeness. Control policy stays in the
  controller; sensing stays here.

## Working on the feedback layer

1. Prefer free / open papers for background links (arXiv, PMC, theses, preprints)
   — see the README reading list.
2. Keep sensing decoupled from actuation: emit readings, don't drive transducers.
3. Fail safe explicitly (`no_reading` / `degraded`); never silently replay stale
   frames as live.
4. Measure per-stage latency; don't assume “real-time.”
5. Exercise changes with synthetic streams (`SignalParams.lifu()`,
   `iter_signals`) and the hydrophone / mock-controller examples:

```bash
pip install -e ".[dev]"
pytest tests/ -q
python examples/hydrophone_ingest.py
python examples/mock_controller.py
```

## Collaboration

If you work on therapeutic ultrasound / PCD / OpenLIFU-class platforms and want
to try the reading contract against your receive path, open an issue or PR with:

- how your controller wants to pull or subscribe
- sample rates / PRF budget you need to hit
- whether you can share synthetic or anonymised channel snippets for calibration
- a human contact who will answer follow-ups on the thread

Hardware bring-up and tissue validation are welcome as collaborations; they are
intentionally out of scope for a pure-software default path.
