# Developer log

globalPCD writes one line per frame on the `pcd` logger. The line is the
reading. It is not the RF samples, and it is not a new schema field.

The library does not configure logging and does not attach a handler that
prints. A host turns the lines on:

```python
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
```

`logging.getLogger("pcd").setLevel(logging.INFO)` enables both loggers below.
Leave the level at WARNING and only deadline misses, faults, and abort
decisions show up.

## `pcd.reading`

`PCDFeedbackEngine.process_frame` writes this after it has a reading and
before it notifies subscribers.

| Level | When | `reason` |
|-------|------|----------|
| INFO | `ok` or `degraded` | `reading` |
| WARNING | deadline missed | `deadline` |
| ERROR | exception while classifying | `fault` |

A fault still returns `no_reading` with regime `unknown`. The traceback is
on the ERROR record (`exc_info`), not in the reading. Controllers keep the
same fail-safe: do not act, and do not replay a previous frame as live.

```
frame=0 t=0.000000 status=ok regime=stable confidence=0.912 latency_ms=1.24 reason=reading loc=null features_ms=0.80 classify_ms=0.11 localize_ms=0.00 sub_amp=0.0123 snr=41.2 ci=0.041
```

`sub_amp`, `snr`, and `ci` are the gates the classifier used (f/2 amplitude,
subharmonic SNR, cavitation index). They are omitted on a fault that happens
before features exist. `snr=inf` means the local noise floor was zero.

## `pcd.monitor`

`run_beside_trigger` writes one line per pulse it considers. A pulse the
engine actually classified also has a `pcd.reading` line. A missed pulse has
no reading and is not replayed.

| Level | When |
|-------|------|
| INFO | pulse accepted, no abort |
| WARNING | missed pulse, or abort requested |

```
pulse=1 due_s=0.100000 missed=true abort=true regime=null
```

## What the log is not

It does not choose the next pulse, arm a transmitter, or replace
`PCDReading.to_dict()`. A session record for a sonication should still store
the reading (regime, confidence, latency, `schema_version`). The log is for
the person bringing the receive path up.
