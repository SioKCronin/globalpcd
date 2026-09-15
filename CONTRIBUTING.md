# Contributing

Thanks for looking at globalPCD. The project is a citizen-science / open
prototype for passive cavitation detection and a controller-facing feedback
layer — meant to be useful to histotripsy and therapeutic-ultrasound groups
without locking anyone into one vendor stack.

## What this repo is (and is not)

- **Is:** synthetic-data toolkit + a `PCDReading` contract a therapy controller
  (e.g. OpenLIFU) can call or subscribe to.
- **Is not:** a pulse sequencer, a treatment planner, or a claim of real-tissue
  validated lesion prediction. Control policy stays in the controller; sensing
  stays here.

## Working on the feedback layer

1. Prefer free / open papers for background links (arXiv, PMC, theses, preprints)
   — see the README reading list.
2. Keep sensing decoupled from actuation: emit readings, don't drive transducers.
3. Fail safe explicitly (`no_reading` / `degraded`); never silently replay stale
   frames as live.
4. Measure per-stage latency; don't assume “real-time.”
5. Exercise changes with synthetic streams (`iter_signals`, `iter_array_frames`)
   and the mocked controller:

```bash
pip install -e ".[dev]"
pytest tests/ -v
python examples/mock_controller.py
```

## Collaboration

If you work on therapeutic ultrasound / PCD / OpenLIFU-class platforms and want
to try the reading contract against your receive path, open an issue or PR with:

- how your controller wants to pull or subscribe
- sample rates / PRF budget you need to hit
- whether you can share synthetic or anonymised channel snippets for calibration

Hardware bring-up and tissue validation are welcome as collaborations; they are
intentionally out of scope for a pure-software default path.
