# PCDReading contract (schema 1.0.0)

This is the piece a therapy controller (OpenLIFU or otherwise) integrates
against. globalPCD decides **what happened acoustically** and **how much to
trust that**. It does not decide the next pulse.

Machine-readable schema: [`pcdreading.schema.json`](pcdreading.schema.json).
Python: `PCDReading.to_dict()` / `SCHEMA_VERSION`.

## Fields

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | string | Currently `"1.0.0"` |
| `frame_id` | int ≥ 0 | Monotonic per engine instance |
| `timestamp` | float | Pulse-trigger time (s), controller clock |
| `status` | `ok` / `degraded` / `no_reading` | See fail-safe below |
| `regime` | `none` / `stable` / `inertial` / `mixed` / `unknown` | Acoustic judgment |
| `confidence` | 0–1 | Distance-to-threshold heuristic (not a calibrated probability) |
| `location_estimate` | number[] or null | Array coords (m); **null for single-element ingest** |
| `location_uncertainty` | number or null | Spot-size proxy (m) |
| `dose_proxy` | number or null | SCD/ICD-style energy proxy |
| `latency_ms` | number ≥ 0 | Measured compute time for this frame |
| `stage_latency_ms` | object | Optional per-stage timings |

## Fail-safe

- **`ok`** — use the reading; still weight by `confidence`.
- **`degraded`** — produced, but low confidence or incomplete (e.g. no location yet). Do not escalate.
- **`no_reading`** — deadline miss or hard fault. **Do not act.** Do not replay a stale frame as live.

Suggested controller mapping for **neuromodulation safety** (research-only):

- `inertial` + high confidence → interlock or step-down
- `no_reading` past a deadline → hold
- `none` → continue under existing MI/pressure limits
- `stable` → caution; policy stays with the platform

## Versioning

- **1.0.0** is the current contract.
- **Patch** (1.0.x): docs/typos only.
- **Minor** (1.x): additive fields; old controllers may ignore unknowns.
- **Major** (2.0): renamed/removed fields or changed enums. Bump `SCHEMA_VERSION` and `$schema` `const`.

Do not fork an Openwater-specific schema; fold their field names into 1.x if needed.

## Scope

Synthetic-calibrated classifier. Not FDA-evaluated. Not a claim that a
label predicts lesion completeness or patient harm. Real-tissue validation
is a separate collaboration.
