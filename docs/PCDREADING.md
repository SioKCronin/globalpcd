# PCDReading contract (schema 1.1.0)

This is the piece a therapy controller (OpenLIFU or otherwise) integrates
against. globalPCD decides **what happened acoustically** and **how much to
trust that**. It does not decide the next pulse.

Machine-readable schema: [`pcdreading.schema.json`](pcdreading.schema.json).
Python: `PCDReading.to_dict()` / `SCHEMA_VERSION`.

## Fields

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | string | Currently `"1.1.0"`; any `1.x` validates |
| `frame_id` | int ≥ 0 | Monotonic per engine instance |
| `timestamp` | float | Pulse-trigger time (s), controller clock |
| `status` | `ok` / `degraded` / `no_reading` | See fail-safe below |
| `regime` | `none` / `stable` / `inertial` / `mixed` / `unknown` | Acoustic judgment |
| `confidence` | 0–1 | Distance-to-threshold heuristic (not a calibrated probability) |
| `location_estimate` | number[] or null | Array coords (m); **null for single-element ingest and for `none`/`unknown` frames** |
| `location_uncertainty` | number or null | Spot-size proxy (m) |
| `dose_proxy` | number or null | SCD/ICD-style energy proxy |
| `latency_ms` | number ≥ 0 | Measured compute time for this frame |
| `stage_latency_ms` | object | Optional per-stage timings |
| `location_frame_id` | int or null | *(1.1.0)* Frame the location was computed on. `== frame_id` when fresh; smaller when carried forward under decimated localization; null with no location. Controllers should check its age before trusting the position. |

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

- **1.1.0** is the current contract (adds optional `location_frame_id`).
- **Patch** (1.x.y): docs/typos only.
- **Minor** (1.x): additive, optional fields only. Consumers **must ignore unknown fields**;
  the JSON Schema allows additional properties and accepts any `1.x.y` version, so a
  1.0 validator keeps working against newer 1.x readings.
- **Major** (2.0): renamed/removed fields or changed enums. Bump `SCHEMA_VERSION` and the
  schema's `schema_version` pattern.

Do not fork an Openwater-specific schema; fold their field names into 1.x if needed.

## Scope

Synthetic-calibrated classifier. Not FDA-evaluated. Not a claim that a
label predicts lesion completeness or patient harm. Real-tissue validation
is a separate collaboration.
